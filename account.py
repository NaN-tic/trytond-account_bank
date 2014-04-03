# This file is part of account_bank module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
from sql import Literal
from sql.operators import Exists
from trytond.model import Workflow, ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool
from trytond.transaction import Transaction
from trytond.wizard import Wizard, StateTransition, StateView, Button

__all__ = [
    'PaymentType',
    'Invoice',
    'Reconciliation',
    'Line',
    'PartialReconcileStart',
    'PartialReconcile',
    ]
__metaclass__ = PoolMeta


class PaymentType:
    __name__ = 'account.payment.type'

    account_bank = fields.Selection([
        ('none', 'None'),
        ('party', 'Party'),
        ('company', 'Company'),
        ], 'Account Bank', select=True, required=True)

    @staticmethod
    def default_account_bank():
        return 'none'


class Invoice:
    __name__ = 'account.invoice'

    account_bank_from = fields.Function(fields.Many2One('party.party',
            'Account Bank From', on_change_with=['party', 'payment_type']),
        'on_change_with_account_bank_from')
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        domain=[
            ('owners', '=', Eval('account_bank_from')),
            ],
        states={
            'readonly': ~Eval('state').in_(['draft', 'validated']),
            'invisible': ~Bool(Eval('account_bank_from')),
            },
        depends=['party', 'payment_type', 'account_bank_from'])

    @classmethod
    def __setup__(cls):
        super(Invoice, cls).__setup__()
        cls.payment_type.on_change = ['payment_type', 'party']
        cls._error_messages.update({
                'invoice_without_bank_account': ('This invoice has no bank '
                    'account associated, but its payment type requires it.')
                })

    def on_change_with_account_bank_from(self, name=None):
        '''
        Sets the party where get bank account for this invoice.
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

    @classmethod
    def _get_bank_account(cls, payment_type, party, company):
        pool = Pool()
        Company = pool.get('company.company')
        Party = pool.get('party.party')

        party_fname = '%s_bank_account' % payment_type.kind
        if hasattr(Party, party_fname):
            account_bank = payment_type.account_bank
            if account_bank == 'company':
                party = company and Company(company).party
            if account_bank in ('company', 'party') and party:
                default_bank = getattr(party, party_fname)
                return default_bank

    def on_change_payment_type(self):
        '''
        Add account bank to account invoice when changes payment_type.
        '''
        res = {'bank_account': None}
        payment_type = self.payment_type
        party = self.party
        company = Transaction().context.get('company')
        if payment_type:
            bank_account = self._get_bank_account(payment_type, party, company)
            res['bank_account'] = bank_account and bank_account.id or None
        return res

    def on_change_party(self):
        '''
        Add account bank to account invoice when changes party.
        '''
        pool = Pool()
        PaymentType = pool.get('account.payment.type')

        res = super(Invoice, self).on_change_party()
        res['bank_account'] = None
        party = self.party
        company = Transaction().context.get('company')
        if res.get('payment_type'):
            payment_type = PaymentType(res['payment_type'])
            bank_account = self._get_bank_account(payment_type, party, company)
            res['bank_account'] = bank_account and bank_account.id or None
        return res

    def _get_move_line(self, date, amount):
        '''
        Add account bank to move line when post invoice.
        '''
        res = super(Invoice, self)._get_move_line(date, amount)
        if self.bank_account:
            res['bank_account'] = self.bank_account
        return res

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        PaymentType = pool.get('account.payment.type')
        Party = pool.get('party.party')
        Company = pool.get('company.company')
        vlist = [x.copy() for x in vlist]
        for values in vlist:
            if (not 'bank_account' in values and 'payment_type' in values
                    and 'party' in values):
                party = Party(values['party'])
                company = Company(values.get('company',
                    Transaction().context.get('company'))).party
                if values.get('payment_type'):
                    payment_type = PaymentType(values['payment_type'])
                    bank_account = cls._get_bank_account(payment_type, party,
                        company)
                    values['bank_account'] = (bank_account and bank_account.id
                        or None)
        return super(Invoice, cls).create(vlist)

    @classmethod
    @ModelView.button
    @Workflow.transition('posted')
    def post(cls, invoices):
        '''
        Check up invoices that requires bank account because its payment type,
        has one
        '''
        for invoice in invoices:
            account_bank = (invoice.payment_type and
                invoice.payment_type.account_bank or 'none')
            if (invoice.payment_type and account_bank != 'none'
                    and not (account_bank in ('party', 'company')
                        and invoice.bank_account)):
                cls.raise_user_error('invoice_without_bank_account')
        super(Invoice, cls).post(invoices)

    def get_lines_to_pay(self, name):
        super(Invoice, self).get_lines_to_pay(name)
        Line = Pool().get('account.move.line')
        if self.type in ('out_invoice', 'out_credit_note'):
            kind = 'receivable'
        else:
            kind = 'payable'
        lines = Line.search([
                ('origin', '=', ('account.invoice', self.id)),
                ('account.kind', '=', kind),
                ('maturity_date', '!=', None),
                ])
        return [x.id for x in lines]


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


class BankMixin:
    account_bank_from = fields.Function(fields.Many2One('party.party',
            'Account Bank From', on_change_with=['party', 'payment_type']),
        'on_change_with_account_bank_from')
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        domain=[
            # TODO: ('owners', '=', Eval('account_bank_from')),
            ],
        states={
                'readonly': Bool(Eval('reconciliation')),
            },
        depends=['party', 'payment_type', 'account_bank_from'])

    @classmethod
    def __setup__(cls):
        super(BankMixin, cls).__setup__()
        cls._error_messages.update({
                'party_without_bank_account': ('%s has no any %s bank '
                    'account.\nPlease set up one if you want to use this '
                    'payment type.'),
                })

    def _get_bank_account(self, payment_type, party, company):
        pool = Pool()
        Company = pool.get('company.company')
        Party = pool.get('party.party')

        party_fname = '%s_bank_account' % payment_type.kind
        if hasattr(Party, party_fname):
            account_bank = payment_type.account_bank
            if account_bank == 'company':
                party = company and Company(company).party
            if account_bank in ('company', 'party') and party:
                default_bank = getattr(party, party_fname)
                if not default_bank:
                    self.raise_user_error('party_without_bank_account',
                        (party.name, payment_type.kind))
                return default_bank

    def on_change_payment_type(self):
        '''
        Add account bank to account invoice when changes payment_type.
        '''
        res = {'bank_account': None}
        payment_type = self.payment_type
        party = self.party
        company = Transaction().context.get('company', False)
        if payment_type:
            bank_account = self._get_bank_account(payment_type, party, company)
            res['bank_account'] = bank_account and bank_account.id or None
        return res

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


class Line(BankMixin):
    __name__ = 'account.move.line'

    reverse_moves = fields.Function(fields.Boolean('With Reverse Moves'),
        'get_reverse_moves', searcher='search_reverse_moves')

    @classmethod
    def __setup__(cls):
        super(Line, cls).__setup__()
        if hasattr(cls, '_check_modify_exclude'):
            cls._check_modify_exclude.append('bank_account')
        cls.payment_type.on_change = ['payment_type', 'party']

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
# Following query isn't working on python-sql, see
# https://code.google.com/p/python-sql/issues/detail?id=17&can=1
#        table = cls.__table__()
#        subtable = cls.__table__()
#
#        zero = Literal(0)
#        query = table.select(table.id, where=Exists(
#                subtable.select(subtable.id,
#                    where=((table.id != subtable.id) &
#                        (table.account == subtable.account) &
#                        (table.party == subtable.party) &
#                        (((table.debit != zero) & (subtable.credit != zero))
#                            | ((table.credit != zero) &
#                                (subtable.debit != zero))) &
#                        (table.reconciliation == None) &
#                        (subtable.reconciliation == None))
#                    )))
#End not working query
        operator = 'in' if clause[2] else 'not in'
#TODO: When issue is fixed uncomment the next line and remove uneeded code.
#        return [('id', operator, query)]
        query = ''
        query += 'SELECT "a"."id" '
        query += 'FROM "account_move_line" AS "a" '
        query += 'INNER JOIN "account_move_line" AS "b" ON '
        query += '"a"."id" != "b"."id" AND '
        query += '    "a"."account" = "b"."account" AND '
        query += '        "a"."party" = "b"."party" AND '
        query += '            (("a"."debit" != 0 AND "b"."credit" != 0) OR '
        query += '            ("a"."credit" != 0 AND "b"."debit" != 0)) AND '
        query += '                "a"."reconciliation" IS NULL AND '
        query += '                    "b"."reconciliation" IS NULL '

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
        company = Transaction().context.get('company', False)
        res['bank_account'] = None
        if res.get('payment_type'):
            payment_type = PaymentType(res['payment_type'])
            bank_account = self._get_bank_account(payment_type, party, company)
            res['bank_account'] = bank_account and bank_account.id or None
        return res


class PartialReconcileStart(ModelView, BankMixin):
    'Partial Reconcile Start'
    __name__ = 'account.move.partial_reconcile.start'
    maturity_date = fields.Date('Maturity Date')
    party = fields.Many2One('party.party', 'Party', readonly=True)
    payment_kind = fields.Char('Payment Kind')
    payment_type = fields.Many2One('account.payment.type', 'Payment Type',
        domain=[
            ('kind', '=', Eval('payment_kind'))
            ],
        depends=['payment_kind'],
        on_change=['party', 'payment_type'])

    @classmethod
    def __setup__(cls):
        super(PartialReconcileStart, cls).__setup__()
        cls._error_messages.update({
                'normal_reconcile': ('Selected moves are balanced. Use concile'
                    ' wizard insted of partial one'),
                'different_parties': ('Parties can not be mixed while partialy'
                    ' reconciling. Party "%s" of line "%s" is diferent from '
                    'previous party "%s"'),
                })

    @staticmethod
    def default_maturity_date():
        pool = Pool()
        return pool.get('ir.date').today()

    @classmethod
    def default_get(cls, fields, with_rec_name=True):
        pool = Pool()
        Line = pool.get('account.move.line')

        res = super(PartialReconcileStart, cls).default_get(fields,
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
        if party:
            res['party'] = party.id
        if amount > 0:
            res['payment_kind'] = 'receivable'
        else:
            res['payment_kind'] = 'payable'
        res['bank_account'] = None
        return res


class PartialReconcile(Wizard):
    'Partial Reconcile'
    __name__ = 'account.move.partial_reconcile'
    start = StateView('account.move.partial_reconcile.start',
        'account_bank.partial_reconcile_lines_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Reconcile', 'reconcile', 'tryton-ok', default=True),
            ])
    reconcile = StateTransition()

    def transition_reconcile(self):
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
        'Returns the counterpart line to create for line'
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
        'Returns the new move to create for lines'
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
