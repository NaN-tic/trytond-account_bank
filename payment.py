# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, If
from trytond.i18n import gettext
from trytond.exceptions import UserError
from trytond.transaction import Transaction
from trytond.modules.currency.fields import Monetary
__all__ = ['Journal', 'Group', 'Payment', 'PayLine']

_ZERO = Decimal(0)


class Journal(metaclass=PoolMeta):
    __name__ = 'account.payment.journal'

    payment_type = fields.Many2One('account.payment.type', 'Payment Type',
        required=True)
    party = fields.Many2One('party.party', 'Party',
        help=('The party who sends the payment group, if it is different from '
        'the company.'),
        context={
            'company': Eval('company', -1),
            }, depends=['company'])


class Group(metaclass=PoolMeta):
    __name__ = 'account.payment.group'

    payment_type = fields.Function(fields.Many2One('account.payment.type',
            'Payment Type'),
        'on_change_with_payment_type')
    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'),
        'on_change_with_currency')

    @fields.depends('journal')
    def on_change_with_payment_type(self, name=None):
        if self.journal and self.journal.payment_type:
            return self.journal.payment_type.id

    @fields.depends('journal', '_parent_journal.currency')
    def on_change_with_currency(self, name=None):
        if self.journal and self.journal.currency:
            return self.journal.currency.id


class Payment(metaclass=PoolMeta):
    __name__ = 'account.payment'
    account_bank_from = fields.Function(fields.Many2One('party.party',
            'Account Bank From', context={
                'company': Eval('company', -1),
            }, depends=['company']),
        'on_change_with_account_bank_from')
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            If(Eval('account_bank_from', None) == None,
                ('id', '=', -1),
                ('owners.id', '=', Eval('account_bank_from')),
                ),
            ])

    @fields.depends('journal', 'party')
    def on_change_with_account_bank_from(self, name=None):
        '''
        Sets the party where get bank account for this account payment.
        '''
        Company = Pool().get('company.company')

        if self.journal and self.journal.payment_type and self.party:
            payment_type = self.journal.payment_type
            party = self.party
            if payment_type.account_bank == 'party':
                return party.id
            elif payment_type.account_bank == 'company':
                company_id = Transaction().context.get('company')
                if company_id is not None and company_id >= 0:
                    return Company(company_id).party.id
            elif payment_type.account_bank == 'other':
                return payment_type.party.id

    @classmethod
    def __setup__(cls):
        super(Payment, cls).__setup__()
        readonly = Eval('state') != 'draft'
        previous_readonly = cls.bank_account.states.get('readonly')
        if previous_readonly:
            readonly = readonly | previous_readonly
        cls.bank_account.states.update({
                'readonly': readonly,
                })

    @fields.depends('party', 'kind')
    def on_change_kind(self):
        super(Payment, self).on_change_kind()
        self.bank_account = None
        party = self.party
        if self.kind and party:
            default_bank_account = getattr(party, self.kind + '_bank_account')
            self.bank_account = (default_bank_account and
                default_bank_account.id or None)

    @fields.depends('party', 'kind')
    def on_change_party(self):
        super(Payment, self).on_change_party()
        self.bank_account = None
        party = self.party
        if party and self.kind:
            default_bank_account = getattr(party, self.kind + '_bank_account')
            self.bank_account = (default_bank_account and
                default_bank_account.id or None)

    @fields.depends('party', 'line', 'kind')
    def on_change_line(self):
        super(Payment, self).on_change_line()
        self.bank_account = None
        party = self.party
        if self.party and self.kind:
            default_bank_account = getattr(party, self.kind + '_bank_account')
            self.bank_account = (default_bank_account and
                default_bank_account.id or None)

    @classmethod
    def get_sepa_mandates(cls, payments):
        mandates = super(Payment, cls).get_sepa_mandates(payments)
        mandates2 = []
        for payment, mandate in zip(payments, mandates):
            if not mandate:
                raise UserError(gettext('account_bank.no_mandate_for_party',
                        payment=payment.rec_name,
                        party=payment.party.rec_name,
                        amount=payment.amount))
            if payment.bank_account != mandate.account_number.account:
                mandate = None
                for mandate2 in payment.party.sepa_mandates:
                    if (mandate2.is_valid and
                        mandate2.account_number.account == payment.bank_account
                        ):
                        mandate = mandate2
                        break
            mandates2.append(mandate)
        return mandates2


class PayLine(metaclass=PoolMeta):
    __name__ = 'account.move.line.pay'

    def get_payment(self, line, journals):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        payment = super(PayLine, self).get_payment(line, journals)
        if hasattr(line, 'bank_account') and line.bank_account:
            payment.bank_account = line.bank_account
        elif isinstance(line.origin, Invoice):
            payment.bank_account = line.origin.bank_account
        return payment
