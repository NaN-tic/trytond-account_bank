# This file is part of account_bank module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from sql import Null
from sql.aggregate import BoolOr
from sql.operators import In
from decimal import Decimal

from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool, If
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.i18n import gettext
from trytond.exceptions import UserError

ACCOUNT_BANK_KIND = [
    ('none', 'None'),
    ('party', 'Party'),
    ('company', 'Company'),
    ('other', 'Other'),
    ]


class PaymentType(metaclass=PoolMeta):
    __name__ = 'account.payment.type'
    account_bank = fields.Selection(ACCOUNT_BANK_KIND, 'Account Bank Kind',
        required=True)
    party = fields.Many2One('party.party', 'Party',
        states={
            'required': Eval('account_bank') == 'other',
            'invisible': Eval('account_bank') != 'other',
            },
        context={
            'company': Eval('company', -1),
            },
        depends=['company'])
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
            })

    @classmethod
    def __setup__(cls):
        super(PaymentType, cls).__setup__()
        cls._check_modify_fields |= set(['account_bank', 'party',
                'bank_account'])

    @staticmethod
    def default_account_bank():
        return 'none'


class BankAccount(metaclass=PoolMeta):
    __name__ = 'bank.account'

    @classmethod
    def __setup__(cls):
        super(BankAccount, cls).__setup__()
        cls._check_owners_fields = set(['owners'])
        cls._check_owners_related_models = set([
                ('account.move.line', 'bank_account'),
                ('account.invoice', 'bank_account'),
                ])

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
        with Transaction().set_context(_check_access=False):
            pool = Pool()
            IrModel = pool.get('ir.model')
            Field = pool.get('ir.model.field')
            account_ids = [a.id for a in accounts]
            for value in cls._check_owners_related_models:
                model_name, field_name = value
                Model = pool.get(model_name)
                records = Model.search([(field_name, 'in', account_ids)])
                model, = IrModel.search([('name', '=', model_name)])
                field, = Field.search([
                        ('model.name', '=', model_name),
                        ('name', '=', field_name),
                        ], limit=1)
                for record in records:
                    target = record.account_bank_from
                    if (not target or (record.payment_type
                            and record.payment_type.account_bank != 'party')):
                        continue
                    account = getattr(record, field_name)
                    if target not in account.owners:
                        raise UserError(gettext(
                            'account_bank.modify_with_related_model',
                            account=account.rec_name,
                            model=model.name,
                            field=field.field_description,
                            name=record.rec_name))


class Party(metaclass=PoolMeta):
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


class BankMixin(object):
    __slots__ = ()
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
        }, ondelete='RESTRICT')

    @fields.depends('payment_type')
    def on_change_with_account_bank(self, name=None):
        if self.payment_type:
            return self.payment_type.account_bank
        return 'none'

    def _get_bank_account(self):
        pool = Pool()
        Party = pool.get('party.party')

        if self.party and self.payment_type:
            if self.payment_type.account_bank == 'none':
                self.bank_account = None
            elif self.payment_type.account_bank == 'other':
                self.bank_account = self.payment_type.bank_account
            else:
                party_fname = '%s_bank_account' % self.payment_type.kind
                if hasattr(Party, party_fname):
                    account_bank = self.payment_type.account_bank
                    if account_bank == 'company':
                        if hasattr(self, 'company') and self.company:
                            available_banks = getattr(self.company.party,
                                'bank_accounts', [])
                            if self.bank_account in available_banks:
                                return
                        party_company_fname = ('%s_company_bank_account' %
                            self.payment_type.kind)
                        company_bank = getattr(self.party, party_company_fname,
                            None)
                        if company_bank:
                            self.bank_account = company_bank
                        elif hasattr(self, 'company') and self.company:
                            default_bank = getattr(
                                self.company.party, party_fname)
                            self.bank_account = default_bank
                        return
                    elif account_bank == 'party' and self.party:
                        default_bank = getattr(self.party, party_fname)
                        if (hasattr(self, 'bank_account') and self.bank_account
                                and self.bank_account == default_bank):
                            return
                        self.bank_account = default_bank
                        return
                    else:
                        self.bank_account = None
                        return
        else:
            self.bank_account = None
            return

    @fields.depends('party', 'payment_type', 'bank_account',
        methods=['on_change_with_payment_type'])
    def on_change_payment_type(self):
        self._get_bank_account()

    @fields.depends('payment_type', 'party',
        methods=['on_change_with_payment_type'])
    def on_change_with_account_bank_from(self, name=None):
        '''
        Sets the party where get bank account for this move line.
        '''
        Company = Pool().get('company.company')

        if self.payment_type and self.party:
            payment_type = self.payment_type
            party = self.party
            if payment_type.account_bank == 'party':
                return party.id
            elif payment_type.account_bank == 'company':
                company_id = Transaction().context.get('company')
                if company_id is not None and company_id >= 0:
                    return Company(company_id).party.id
            elif payment_type.account_bank == 'other':
                return payment_type.party.id


class Invoice(BankMixin, metaclass=PoolMeta):
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
        cls.account_bank_from.context = {'company': Eval('company', -1)}
        cls.account_bank_from.depends = ['company']
        # allow process or paid invoices when is posted
        cls._check_modify_exclude.add('bank_account')
        cls.bank_account.domain = [
            If(Eval('state').in_(['draft', 'validated']),
               cls.bank_account.domain,
               ())
            ]

    @fields.depends('payment_type', 'party', 'company', 'bank_account')
    def on_change_party(self):
        '''
        Add account bank to invoice line when changes party.
        '''
        super(Invoice, self).on_change_party()
        self.bank_account = None
        if self.payment_type:
            self._get_bank_account()

    @classmethod
    def post(cls, invoices):
        '''
        Check up invoices that requires bank account because its payment type,
        has one
        '''
        to_save = []
        for invoice in invoices:
            account_bank = (invoice.payment_type and
                invoice.payment_type.account_bank or 'none')
            if (invoice.payment_type and account_bank != 'none'
                    and not invoice.bank_account):
                invoice._get_bank_account()
                if not invoice.bank_account:
                    raise UserError(gettext(
                        'account_bank.invoice_without_bank_account',
                            invoice=invoice.rec_name,
                            payment_type=invoice.payment_type.rec_name))

                to_save.append(invoice)
        if to_save:
            cls.save(to_save)
        super(Invoice, cls).post(invoices)

    def _get_move_line(self, date, amount):
        '''Add account bank to move line when post invoice.'''
        line = super(Invoice, self)._get_move_line(date, amount)
        if self.bank_account:
            line.bank_account = self.bank_account
        return line

    @fields.depends('payment_type', 'party', 'company', 'bank_account')
    def on_change_lines(self):
        super().on_change_lines()
        self.bank_account = None
        if self.payment_type:
            self._get_bank_account()


class Line(BankMixin, metaclass=PoolMeta):
    __name__ = 'account.move.line'

    reverse_moves = fields.Function(fields.Boolean('With Reverse Moves'),
        'get_reverse_moves', searcher='search_reverse_moves')
    netting_moves = fields.Function(fields.Boolean('With Netting Moves'),
        'get_netting_moves', searcher='search_netting_moves')

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
        cls.account_bank_from.context = {'company': Eval('company', -1)}
        cls.account_bank_from.depends.add('company')

    @fields.depends('party', 'payment_type', 'bank_account')
    def on_change_party(self):
        '''Add account bank to account move line when changes party.'''
        try:
            super(Line, self).on_change_party()
        except AttributeError:
            pass
        if self.payment_type and self.party:
            self._get_bank_account()

    @fields.depends('party', 'account_kind', 'move', '_parent_move.id')
    def on_change_with_payment_type(self, name=None):
        if self.party:
            if self.account_kind == 'payable':
                return (self.party.supplier_payment_type.id
                    if self.party.supplier_payment_type else None)
            elif self.account_kind == 'receivable':
                return (self.party.customer_payment_type.id
                    if self.party.customer_payment_type else None)

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        if (Transaction().context.get('cancel_move')
                and 'bank_account' not in default):
            default['bank_account'] = None
        return super(Line, cls).copy(lines, default)

    def get_reverse_moves(self, name):
        if (not self.account
                or (self.account.type.receivable == False and
                    self.account.type.payable == False)):
            return False
        domain = [
            ('account', '=', self.account.id),
            ('reconciliation', '=', None),
            ]
        if self.party:
            domain.append(('party', '=', self.party.id))
        if self.credit > Decimal(0):
            domain.append(('debit', '>', 0))
        if self.debit > Decimal(0):
            domain.append(('credit', '>', 0))
        moves = self.search(domain, limit=1)
        return len(moves) > 0

    @classmethod
    def search_reverse_moves(cls, name, clause):
        pool = Pool()
        Account = pool.get('account.account')
        MoveLine = pool.get('account.move.line')
        operator = 'in' if clause[2] else 'not in'
        lines = MoveLine.__table__()
        move_line = MoveLine.__table__()
        account = Account.__table__()
        cursor = Transaction().connection.cursor()

        reverse = move_line.join(account, condition=(
                account.id == move_line.account)).select(
                    move_line.account, move_line.party,
                    where=(account.reconcile
                        & (move_line.reconciliation == Null)),
                    group_by=(move_line.account, move_line.party),
                    having=((BoolOr((move_line.debit) != Decimal(0)))
                        & (BoolOr((move_line.credit) != Decimal(0))))
                    )
        query = lines.select(lines.id, where=(
                In((lines.account, lines.party), reverse)))
        # Fetch the data otherwise its too slow
        cursor.execute(*query)

        return [('id', operator, [x[0] for x in cursor.fetchall()])]

    def get_netting_moves(self, name):
        if (not self.account
                or (self.account.type.receivable == False and
                    self.account.type.payable == False)):
            return False
        if not self.account.party_required:
            return False
        domain = [
            ('party', '=', self.party.id),
            ('reconciliation', '=', None),
            ['OR',
                ('debit', '!=', 0),
                ('credit', '!=', 0),
            ],
            ['OR',
                ('account.type.receivable', '=', True),
                ('account.type.payable', '=', True)
            ],
            ('move.company', '=', self.move.company)
            ]
        moves = self.search(domain, limit=1)
        return len(moves) > 0

    @classmethod
    def search_netting_moves(cls, name, clause):
        pool = Pool()
        Account = pool.get('account.account')
        MoveLine = pool.get('account.move.line')
        Move = pool.get('account.move')
        AccountType = pool.get('account.account.type')
        Rule = pool.get('ir.rule')
        operator = 'in' if clause[2] else 'not in'
        lines = MoveLine.__table__()
        move = Move.__table__()
        move_line = MoveLine.__table__()
        account = Account.__table__()
        account_type = AccountType.__table__()
        cursor = Transaction().connection.cursor()

        companies = Rule._get_context(cls.__name__).get('companies')
        if not companies:
            companies = [-1]
        company_filter = move.company.in_(companies)

        netting = move_line.join(account, condition=(
                account.id == move_line.account)).join(move, condition=(
                    move.id == move_line.move)).join(account_type, condition=(
                        account_type.id == account.type)).select(
                    move.company, move_line.party,
                    where=(account.reconcile
                        & (move_line.reconciliation == Null)
                        & (move.state == 'posted')
                        & (account_type.receivable | account_type.payable)
                        & (move_line.party != Null))
                        & company_filter,
                    group_by=(move_line.party, move.company),
                    having=((BoolOr((move_line.debit) != Decimal(0)))
                        & (BoolOr((move_line.credit) != Decimal(0))))
                    )
        query = lines.join(move, condition=(move.id == lines.move)).select(lines.id, where=(
                In((move.company, lines.party), netting)))
        # Fetch the data otherwise its too slow
        cursor.execute(*query)

        return [('id', operator, [x[0] for x in cursor.fetchall()])]

    @fields.depends('_parent_move.id')
    def on_change_with_account_bank_from(self, name=None):
        return super().on_change_with_account_bank_from(name)

    def get_payment_kind(self, name):
        # From https://discuss.tryton.org/t/field-amount-to-pay-in-account-payment/6561/7
        kind = super().get_payment_kind(name)
        if not kind:
            if self.account.type.receivable:
                kind = 'receivable'
            elif self.account.type.payable:
                kind = 'payable'
        return kind


class CompensationMoveStart(ModelView, BankMixin):
    'Create Compensation Move Start'
    __name__ = 'account.move.compensation_move.start'
    party = fields.Many2One('party.party', 'Party', readonly=True)
    account = fields.Many2One('account.account', 'Account',
        domain=[
            ('company', '=', Eval('context', {}).get('company', -1)),
            ['OR',
                ('type.receivable', '=', True),
                ('type.payable','=', True)]],
        required=True)
    date = fields.Date('Date')
    maturity_date = fields.Date('Maturity Date')
    description = fields.Char('Description')
    payment_kind = fields.Selection([
            ('both', 'Both'),
            ('payable', 'Payable'),
            ('receivable', 'Receivable'),
            ], 'Payment Kind')
    payment_type = fields.Many2One('account.payment.type', 'Payment Type',
        domain=[
            ('kind', '=', Eval('payment_kind'))
            ])

    @staticmethod
    def default_date():
        pool = Pool()
        return pool.get('ir.date').today()

    @staticmethod
    def default_maturity_date():
        pool = Pool()
        return pool.get('ir.date').today()

    @classmethod
    def default_get(
            cls, fields_names=None, with_rec_name=True, with_default=True):
        pool = Pool()
        Line = pool.get('account.move.line')
        PaymentType = pool.get('account.payment.type')

        defaults = super().default_get(
            fields_names=fields_names,
            with_rec_name=with_rec_name,
            with_default=with_default)

        party = None
        company = None
        amount = Decimal(0)

        lines = Line.browse(Transaction().context.get('active_ids', []))
        for line in lines:
            amount += line.debit - line.credit
            if not party:
                party = line.party
            elif party != line.party:
                raise UserError(gettext('account_bank.different_parties',
                        party=line.party.rec_name, line=line.rec_name,
                        previous_party=party.rec_name))
            if not company:
                company = line.account.company
        if (company and company.currency.is_zero(amount)
                and len(set([x.account for x in lines])) == 1):
            raise UserError(gettext('account_bank.normal_reconcile'))
        if amount > 0:
            defaults['payment_kind'] = 'receivable'
        else:
            defaults['payment_kind'] = 'payable'
        defaults['bank_account'] = None
        if party:
            defaults['party'] = party.id
            if (defaults['payment_kind'] in ['receivable', 'both']
                    and party.customer_payment_type):
                defaults['payment_type'] = party.customer_payment_type.id
            elif (defaults['payment_kind'] in ['payable', 'both']
                    and party.supplier_payment_type):
                defaults['payment_type'] = party.supplier_payment_type.id
            if defaults.get('payment_type'):
                payment_type = PaymentType(defaults['payment_type'])
                defaults['account_bank'] = payment_type.account_bank

                self = cls()
                self.payment_type = payment_type
                self.party = party
                self._get_bank_account()
                defaults['account_bank_from'] = (
                    self.on_change_with_account_bank_from())
                defaults['bank_account'] = (self.bank_account.id
                    if hasattr(self, 'bank_account') and self.bank_account else None)
            if amount > 0:
                defaults['account'] = (party.account_receivable.id
                    if party.account_receivable else None)
            else:
                defaults['account'] = (party.account_payable.id
                    if party.account_payable else None)
        return defaults

    def on_change_with_payment_type(self, name=None):
        pass


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
            if ((line.account.type.receivable == False and
                    line.account.type.payable == False)
                    or line.reconciliation):
                continue
            move_lines.append(self.get_counterpart_line(line))

        if not lines or not move_lines:
            return 'end'

        move = self.get_move(lines)
        extra_lines, origin = self.get_extra_lines(lines, self.start.account,
            self.start.party)

        if origin:
            move.origin = origin
        move.lines = move_lines + extra_lines
        move.save()
        Move.post([move])
        to_reconcile = {}
        for line in lines:
            to_reconcile.setdefault(line.account.id, []).append(line)
        for line in move.lines:
            append = True
            for extra_line in extra_lines:
                if self.is_extra_line(line, extra_line):
                    append = False
                    break
            if append:
                to_reconcile.setdefault(line.account.id, []).append(line)
        for lines_to_reconcile in to_reconcile.values():
            Line.reconcile(lines_to_reconcile)
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
        new_line.second_currency = line.second_currency
        if line.second_currency:
            new_line.amount_second_currency = -line.amount_second_currency
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
        move.description = self.start.description

        return move

    def get_extra_lines(self, lines, account, party=None):
        'Returns extra lines to balance move and move origin'
        pool = Pool()
        Line = pool.get('account.move.line')

        amount = Decimal(0)
        origins = {}
        for line in lines:
            line_amount = line.debit - line.credit
            amount += line_amount
            move_origin = line.move_origin
            if move_origin:
                if move_origin not in origins:
                    origins[move_origin] = Decimal(0)
                origins[move_origin] += abs(line_amount)

        if not account:
            return ([], None)

        extra_line = Line()
        extra_line.account = account
        extra_line.party = party
        extra_line.maturity_date = self.start.maturity_date
        extra_line.payment_type = self.start.payment_type
        extra_line.bank_account = self.start.bank_account
        extra_line.description = self.start.description
        extra_line.credit = extra_line.debit = Decimal(0)
        if amount > 0:
            extra_line.debit = amount
        else:
            extra_line.credit = abs(amount)

        origin = None
        for line_origin, line_amount in sorted(origins.items(),
                key=lambda x: x[1]):
            if abs(amount) < line_amount:
                origin = line_origin
                break
        return [extra_line], origin
