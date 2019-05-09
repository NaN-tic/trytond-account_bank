# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Journal', 'Group', 'Payment', 'PayLine']

_ZERO = Decimal('0.0')


class Journal(metaclass=PoolMeta):
    __name__ = 'account.payment.journal'

    payment_type = fields.Many2One('account.payment.type', 'Payment Type',
        required=True)
    party = fields.Many2One('party.party', 'Party',
        help=('The party who sends the payment group, if it is different from '
        'the company.'))


class Group(metaclass=PoolMeta):
    __name__ = 'account.payment.group'

    payment_type = fields.Function(fields.Many2One('account.payment.type',
            'Payment Type'),
        'on_change_with_payment_type')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    amount = fields.Function(fields.Numeric('Total', digits=(16,
                Eval('currency_digits', 2)), depends=['currency_digits']),
        'get_amount')

    @classmethod
    def default_currency_digits(cls):
        return 2

    @fields.depends('journal')
    def on_change_with_payment_type(self, name=None):
        if self.journal and self.journal.payment_type:
            return self.journal.payment_type.id

    @fields.depends('journal')
    def on_change_with_currency_digits(self, name=None):
        if self.journal and self.journal.currency:
            return self.journal.currency.digits
        return 2

    def get_amount(self, name):
        amount = _ZERO
        for payment in self.payments:
            amount += payment.amount
        if self.journal and self.journal.currency:
            return self.journal.currency.round(amount)
        else:
            return amount


class Payment(metaclass=PoolMeta):
    __name__ = 'account.payment'
    bank_account = fields.Many2One('bank.account', 'Bank Account',
        states={
            'readonly': Eval('state') != 'draft',
            },
        domain=[
            ('owners', '=', Eval('party'))
            ],
        depends=['party', 'kind'])

    @classmethod
    def __setup__(cls):
        super(Payment, cls).__setup__()
        if 'party' not in cls.kind.on_change:
            cls.kind.on_change.add('party')
        if 'kind' not in cls.party.on_change:
            cls.party.on_change.add('kind')
        if 'kind' not in cls.line.on_change:
            cls.line.on_change.add('kind')
        if 'party' not in cls.line.on_change:
            cls.line.on_change.add('party')
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

    @fields.depends('party', 'line')
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
