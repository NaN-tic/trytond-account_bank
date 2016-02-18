# This file is part of account_bank module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from sql import Cast
from sql.operators import Concat
from sql.conditionals import Case
from decimal import Decimal

from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool, If
from trytond.transaction import Transaction
from trytond.tools import grouped_slice, reduce_ids
from trytond.wizard import Wizard, StateTransition, StateView, Button

__all__ = ['PaymentType', 'BankAccount', 'Party', 'Invoice', 'Reconciliation',
    'Line', 'CompensationMoveStart', 'CompensationMove']
__metaclass__ = PoolMeta

ACCOUNT_BANK_KIND = [
    ('none', 'None'),
    ('party', 'Party'),
    ('company', 'Company'),
    ('other', 'Other'),
    ]


class PaymentType:
    __name__ = 'account.payment.type'
    account_bank = fields.Selection(ACCOUNT_BANK_KIND, 'Account Bank',
        select=True, required=True)
    party = fields.Many2One('party.party', 'Party',
        states={
            'required': Eval('account_bank') == 'other',
            'invisible': Eval('account_bank') != 'other',
            },
        depends=['account_bank'])
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        domain=[
            If(Eval('party', None) == None,
                ('id', '=', -1),
                ('owners.id', '=', Eval('party')),
                ),
            ],
        states={
            'required': Eval('account_bank') == 'other',
            'invisible': Eval('account_bank') != 'other',
            },
        depends=['party', 'account_bank'])

    @classmethod
    def __setup__(cls):
        super(PaymentType, cls).__setup__()
        cls._check_modify_fields |= set(['account_bank', 'party',
                'bank_account'])

    @staticmethod
    def default_account_bank():
        return 'none'


class BankAccount:
    __name__ = 'bank.account'

    @classmethod
    def __setup__(cls):
        super(BankAccount, cls).__setup__()
        cls._check_owners_fields = set(['owners'])
        cls._check_owners_related_models = set([
                ('account.move.line', 'bank_account'),
                ('account.invoice', 'bank_account'),
                ])
        cls._error_messages.update({
                'modifiy_with_related_model': ('It is not possible to modify '
                    'the owner of bank account "%(account)s" as it is used on '
                    'en el %(field)s del %(model)s "%(name)s"'),
                })

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        all_accounts = []
        for accounts, values in zip(actions, actions):
            if set(values.keys()) & cls._check_owners_fields:
                all_accounts += accounts
        super(BankAccount, cls).write(*args)
        cls.check_owners(all_accounts)

    @classmethod
    def check_owners(cls, accounts):
        pool = Pool()
        IrModel = pool.get('ir.model')
        Field = pool.get('ir.model.field')
        account_ids = [a.id for a in accounts]
        for value in cls._check_owners_related_models:
            model_name, field_name = value
            Model = pool.get(model_name)
            records = Model.search([(field_name, 'in', account_ids)])
            model, = IrModel.search([('model', '=', model_name)])
            field, = Field.search([
                    ('model.model', '=', model_name),
                    ('name', '=', field_name),
                    ], limit=1)
            for record in records:
                target = record.account_bank_from
                account = getattr(record, field_name)
                if target not in account.owners:
                    error_args = {
                        'account': account.rec_name,
                        'model': model.name,
                        'field': field.field_description,
                        'name': record.rec_name,
                        }
                    cls.raise_user_error('modifiy_with_related_model',
                        error_args)


class Party:
    __name__ = 'party.party'

    @classmethod
    def write(cls, *args):
        pool = Pool()
        BankAccount = pool.get('bank.account')
        actions = iter(args)
        all_accounts = []
        for parties, values in zip(actions, actions):
            if set(values.keys()) & set(['bank_accounts']):
                all_accounts += list(set(
                        [a for p in parties for a in p.bank_accounts]))
        super(Party, cls).write(*args)
        BankAccount.check_owners(all_accounts)


class BankMixin:
    account_bank = fields.Function(fields.Selection(ACCOUNT_BANK_KIND,
            'Account Bank'),
        'on_change_with_account_bank')
    account_bank_from = fields.Function(fields.Many2One('party.party',
            'Account Bank From'),
        'on_change_with_account_bank_from')
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        domain=[
            If(Eval('account_bank_from', None) == None,
                ('id', '=', -1),
                ('owners.id', '=', Eval('account_bank_from')),
                ),
            ],
        states={
                'readonly': Eval('account_bank') == 'other',
                'invisible': ~Bool(Eval('account_bank_from')),
            },
        depends=['party', 'payment_type', 'account_bank_from', 'account_bank'],
        ondelete='RESTRICT')

    @classmethod
    def __setup__(cls):
        super(BankMixin, cls).__setup__()
        cls._error_messages.update({
                'party_without_bank_account': ('%s has no any %s bank '
                    'account.\nPlease set up one if you want to use this '
                    'payment type.'),
                })

    @fields.depends('payment_type')
    def on_change_with_account_bank(self, name=None):
        if self.payment_type:
            return self.payment_type.account_bank

    @classmethod
    def _get_bank_account(cls, payment_type, party, company):
        pool = Pool()
        Company = pool.get('company.company')
        Party = pool.get('party.party')

        if payment_type.account_bank == 'other':
            return payment_type.bank_account

        party_fname = '%s_bank_account' % payment_type.kind
        if hasattr(Party, party_fname):
            account_bank = payment_type.account_bank
            if account_bank == 'company':
                party_company_fname = ('%s_company_bank_account' %
                    payment_type.kind)
                company_bank = getattr(party, party_company_fname, None)
                if company_bank:
                    return company_bank
                party = company and Company(company).party
            if account_bank in ('company', 'party') and party:
                default_bank = getattr(party, party_fname)
                return default_bank

    @fields.depends('payment_type', 'party')
    def on_change_with_bank_account(self):
        '''
        Add account bank when changes payment_type or party.
        '''
        res = None
        payment_type = self.payment_type
        party = self.party
        company = Transaction().context.get('company')
        if payment_type:
            bank_account = self._get_bank_account(payment_type, party, company)
            res = bank_account and bank_account.id or None
        return res

    @fields.depends('payment_type', 'party')
    def on_change_with_account_bank_from(self, name=None):
        '''
        Sets the party where get bank account for this move line.
        '''
        pool = Pool()
        Company = pool.get('company.company')
        if self.payment_type and self.party:
            payment_type = self.payment_type
            party = self.party
            if payment_type.account_bank == 'party':
                return party.id
            elif payment_type.account_bank == 'company':
                company = Transaction().context.get('company', False)
                return Company(company).party.id
            elif payment_type.account_bank == 'other':
                return payment_type.party.id


class Invoice(BankMixin):
    __name__ = 'account.invoice'

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        readonly = ~Eval('state').in_(['draft', 'validated'])
        previous_readonly = cls.bank_account.states.get('readonly')
        if previous_readonly:
            readonly = readonly | previous_readonly
        cls.bank_account.states.update({
                'readonly': readonly,
                })
        cls._error_messages.update({
                'invoice_without_bank_account': ('Invoice "%(invoice)s" has no '
                    'bank account associated but payment type '
                    '"%(payment_type)s" requires it.'),
                })

    def _get_move_line(self, date, amount):
        '''
        Add account bank to move line when post invoice.
        '''
        res = super(Invoice, self)._get_move_line(date, amount)
        if self.bank_account:
            res['bank_account'] = self.bank_account
        return res

    @classmethod
    def compute_default_bank_account(cls, values):
        pool = Pool()
        PaymentType = pool.get('account.payment.type')
        Party = pool.get('party.party')
        changes = {}
        if (not 'bank_account' in values and 'payment_type' in values
                and 'party' in values):
            party = Party(values['party'])
            company = values.get('company',
                Transaction().context.get('company'))
            if values.get('payment_type'):
                payment_type = PaymentType(values['payment_type'])
                bank_account = cls._get_bank_account(payment_type, party,
                    company)
                changes['bank_account'] = (bank_account and bank_account.id
                    or None)
        return changes

    @classmethod
    def create(cls, vlist):
        vlist = [x.copy() for x in vlist]
        for values in vlist:
            values.update(cls.compute_default_bank_account(values))
        return super(Invoice, cls).create(vlist)

    @fields.depends('payment_type', 'party', 'company')
    def on_change_party(self):
        '''
        Add account bank to invoice line when changes party.
        '''
        changes = super(Invoice, self).on_change_party()
        if 'payment_type' in changes:
            self.payment_type = changes['payment_type']
        changes['bank_account'] = None
        if self.payment_type:
            bank_account = self._get_bank_account(self.payment_type,
                self.party, self.company)
            changes['bank_account'] = bank_account and bank_account.id or None
        return changes

    @classmethod
    def post(cls, invoices):
        '''
        Check up invoices that requires bank account because its payment type,
        has one
        '''
        for invoice in invoices:
            account_bank = (invoice.payment_type and
                invoice.payment_type.account_bank or 'none')
            if (invoice.payment_type and account_bank != 'none'
                    and not invoice.bank_account):
                cls.raise_user_error('invoice_without_bank_account', {
                        'invoice': invoice.rec_name,
                        'payment_type': invoice.payment_type.rec_name,
                        })

        super(Invoice, cls).post(invoices)

    @classmethod
    def get_lines_to_pay(cls, invoices, name):
        pool = Pool()
        Move = pool.get('account.move')
        Line = pool.get('account.move.line')
        Account = pool.get('account.account')
        line = Line.__table__()
        account = Account.__table__()
        move = Move.__table__()
        invoice = cls.__table__()
        cursor = Transaction().cursor
        _, origin_type = Move.origin.sql_type()

        lines = super(Invoice, cls).get_lines_to_pay(invoices, name)
        for sub_ids in grouped_slice(invoices):
            red_sql = reduce_ids(invoice.id, sub_ids)
            query = invoice.join(move,
                condition=((move.origin == Concat('account.invoice,',
                                Cast(invoice.id, origin_type))))
                    ).join(line, condition=(line.move == move.id)
                    ).join(account, condition=(
                        (line.account == account.id) &
                        Case((invoice.type.in_(
                                ['out_invoice', 'out_credit_note']),
                            account.kind == 'receivable'),
                            else_=account.kind == 'payable'))).select(
                    invoice.id, line.id,
                    where=(line.maturity_date != None) & red_sql,
                    order_by=(invoice.id, line.maturity_date))
            cursor.execute(*query)
            for invoice_id, line_id in cursor.fetchall():
                if not line_id in lines[invoice_id]:
                    lines[invoice_id].append(line_id)
        return lines


class Reconciliation:
    __name__ = 'account.move.reconciliation'

    @classmethod
    def create(cls, vlist):
        Invoice = Pool().get('account.invoice')
        reconciliations = super(Reconciliation, cls).create(vlist)
        moves = set()
        for reconciliation in reconciliations:
            moves |= set(l.move for l in reconciliation.lines)
        invoices = []
        for move in moves:
            if (move.origin and isinstance(move.origin, Invoice)
                    and move.origin.state == 'posted'):
                invoices.append(move.origin)
        if invoices:
            Invoice.process(invoices)
        return reconciliations

    @classmethod
    def delete(cls, reconciliations):
        Invoice = Pool().get('account.invoice')

        moves = set()
        for reconciliation in reconciliations:
            moves |= set(l.move for l in reconciliation.lines)
        invoices = []
        for move in moves:
            if move.origin and isinstance(move.origin, Invoice):
                invoices.append(move.origin)
        super(Reconciliation, cls).delete(reconciliations)
        if invoices:
            Invoice.process(invoices)


class Line(BankMixin):
    __name__ = 'account.move.line'

    reverse_moves = fields.Function(fields.Boolean('With Reverse Moves'),
        'get_reverse_moves', searcher='search_reverse_moves')

    @classmethod
    def __setup__(cls):
        super(Line, cls).__setup__()
        if hasattr(cls, '_check_modify_exclude'):
            cls._check_modify_exclude.add('bank_account')
        readonly = Bool(Eval('reconciliation'))
        previous_readonly = cls.bank_account.states.get('readonly')
        if previous_readonly:
            readonly = readonly | previous_readonly
        cls.bank_account.states.update({
                'readonly': readonly,
                })

    def get_reverse_moves(self, name):
        if (not self.account or not self.account.kind in
                ['receivable', 'payable']):
            return False
        domain = [
            ('account', '=', self.account.id),
            ('reconciliation', '=', None),
            ]
        if self.party:
            domain.append(('party', '=', self.party.id))
        if self.credit > Decimal('0.0'):
            domain.append(('debit', '>', 0))
        if self.debit > Decimal('0.0'):
            domain.append(('credit', '>', 0))
        moves = self.search(domain, limit=1)
        return len(moves) > 0

    @classmethod
    def search_reverse_moves(cls, name, clause):
        operator = 'in' if clause[2] else 'not in'
        query = """
            SELECT
                id
            FROM
                account_move_line l
            WHERE
                (account, party) IN (
                    SELECT
                        aa.id,
                        aml.party
                    FROM
                        account_account aa,
                        account_move_line aml
                    WHERE
                        aa.reconcile
                        AND aa.id = aml.account
                        AND aml.reconciliation IS NULL
                    GROUP BY
                        aa.id,
                        aml.party
                    HAVING
                        bool_or(aml.debit <> 0)
                        AND bool_or(aml.credit <> 0)
                    )
            """
        cursor = Transaction().cursor
        cursor.execute(query)
        return [('id', operator, [x[0] for x in cursor.fetchall()])]

    def on_change_party(self):
        '''
        Add account bank to account move line when changes party.
        '''
        pool = Pool()
        PaymentType = pool.get('account.payment.type')

        res = super(Line, self).on_change_party()
        party = self.party
        company = Transaction().context.get('company')
        res['bank_account'] = None
        if res.get('payment_type'):
            payment_type = PaymentType(res['payment_type'])
            bank_account = self._get_bank_account(payment_type, party, company)
            res['bank_account'] = bank_account and bank_account.id or None
        return res

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        if (Transaction().context.get('cancel_move') and not 'bank_account' in
                default):
            default['bank_account'] = None
        return super(Line, cls).copy(lines, default)


class CompensationMoveStart(ModelView, BankMixin):
    'Create Compensation Move Start'
    __name__ = 'account.move.compensation_move.start'
    maturity_date = fields.Date('Maturity Date')
    party = fields.Many2One('party.party', 'Party', readonly=True)
    payment_kind = fields.Char('Payment Kind')
    payment_type = fields.Many2One('account.payment.type', 'Payment Type',
        domain=[
            ('kind', '=', Eval('payment_kind'))
            ],
        depends=['payment_kind'])

    @classmethod
    def __setup__(cls):
        super(CompensationMoveStart, cls).__setup__()
        cls._error_messages.update({
                'normal_reconcile': ('Selected moves are balanced. Use concile '
                    'wizard instead of creating a compensation move.'),
                'different_parties': ('Parties can not be mixed to create a '
                    'compensation move. Party "%s" in line "%s" is different '
                    'from previous party "%s"'),
                })

    @staticmethod
    def default_maturity_date():
        pool = Pool()
        return pool.get('ir.date').today()

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        Line = pool.get('account.move.line')
        PaymentType = pool.get('account.payment.type')

        res = super(CompensationMoveStart, cls).default_get(fields,
            with_rec_name)

        party = None
        company = None
        amount = Decimal('0.0')

        for line in Line.browse(Transaction().context.get('active_ids', [])):
            amount += line.debit - line.credit
            if not party:
                party = line.party
            elif party != line.party:
                cls.raise_user_error('different_parties', (line.party.rec_name,
                        line.rec_name, party.rec_name))
            if not company:
                company = line.account.company
        if company and company.currency.is_zero(amount):
            cls.raise_user_error('normal_reconcile')
        if amount > 0:
            res['payment_kind'] = 'receivable'
        else:
            res['payment_kind'] = 'payable'
        res['bank_account'] = None
        if party:
            res['party'] = party.id
            if (res['payment_kind'] == 'receivable' and
                    party.customer_payment_type):
                res['payment_type'] = party.customer_payment_type.id
            elif (res['payment_kind'] == 'payable' and
                    party.supplier_payment_type):
                res['payment_type'] = party.supplier_payment_type.id
            if 'payment_type' in res:
                payment_type = PaymentType(res['payment_type'])
                res['account_bank'] = payment_type.account_bank
                self = cls()
                self.payment_type = payment_type
                self.party = party
                res['account_bank_from'] = (
                    self.on_change_with_account_bank_from())
                bank_account = cls._get_bank_account(payment_type, party,
                    company.id)
                if bank_account:
                    res['bank_account'] = bank_account.id
        return res


class CompensationMove(Wizard):
    'Create Compensation Move'
    __name__ = 'account.move.compensation_move'
    start = StateView('account.move.compensation_move.start',
        'account_bank.compensation_move_lines_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Create', 'create_move', 'tryton-ok', default=True),
            ])
    create_move = StateTransition()

    def transition_create_move(self):
        pool = Pool()
        Move = pool.get('account.move')
        Line = pool.get('account.move.line')

        move_lines = []
        lines = Line.browse(Transaction().context.get('active_ids'))

        for line in lines:
            if (not line.account.kind in ('payable', 'receivable') or
                    line.reconciliation):
                continue
            move_lines.append(self.get_counterpart_line(line))

        if not lines or not move_lines:
            return

        move = self.get_move(lines)
        extra_lines, origin = self.get_extra_lines(lines)

        if origin:
            move.origin = origin
        move.lines = move_lines + extra_lines
        move.save()
        Move.post([move])
        for line in move.lines:
            append = True
            for extra_line in extra_lines:
                if self.is_extra_line(line, extra_line):
                    append = False
                    break
            if append:
                lines.append(line)

        Line.reconcile(lines)
        return 'end'

    def is_extra_line(self, line, extra_line):
        " Returns true if both lines are equal"
        return (line.debit == extra_line.debit and
            line.credit == extra_line.credit and
            line.maturity_date == extra_line.maturity_date and
            line.payment_type == extra_line.payment_type and
            line.bank_account == extra_line.bank_account)

    def get_counterpart_line(self, line):
        'Returns the counterpart line to create from line'
        pool = Pool()
        Line = pool.get('account.move.line')

        new_line = Line()
        new_line.account = line.account
        new_line.debit = line.credit
        new_line.credit = line.debit
        new_line.description = line.description
        new_line.second_curency = line.second_currency
        new_line.amount_second_currency = line.amount_second_currency
        new_line.party = line.party

        return new_line

    def get_move(self, lines):
        'Returns the new move to create from lines'
        pool = Pool()
        Move = pool.get('account.move')
        Period = pool.get('account.period')
        Date = pool.get('ir.date')

        period_id = Period.find(lines[0].account.company.id)
        move = Move()
        move.period = Period(period_id)
        move.journal = lines[0].move.journal
        move.date = Date.today()

        return move

    def get_extra_lines(self, lines):
        'Returns extra lines to balance move and move origin'
        pool = Pool()
        Line = pool.get('account.move.line')

        amount = Decimal('0.0')
        origins = {}
        account = None
        party = None
        for line in lines:
            line_amount = line.debit - line.credit
            amount += line_amount
            if line.origin:
                if line.origin not in origins:
                    origins[line.origin] = Decimal('0.0')
                origins[line.origin] += abs(line_amount)
            if not account:
                account = line.account
            if not party:
                party = line.party

        if not account or not party:
            ([], None)

        extra_line = Line()
        extra_line.account = account
        extra_line.party = party
        extra_line.maturity_date = self.start.maturity_date
        extra_line.payment_type = self.start.payment_type
        extra_line.bank_account = self.start.bank_account
        extra_line.credit = extra_line.debit = Decimal('0.0')
        if amount > 0:
            extra_line.debit = amount
        else:
            extra_line.credit = abs(amount)

        origin = None
        for line_origin, line_amount in sorted(origins.iteritems(),
                key=lambda x: x[1]):
            if abs(amount) < line_amount:
                origin = line_origin
                break
        return [extra_line], origin
