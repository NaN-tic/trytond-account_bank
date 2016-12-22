# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal

from trytond.model import fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from .account import BankMixin

__all__ = ['Journal', 'Group', 'Payment', 'PayLine']

_ZERO = Decimal('0.0')


class Journal:
    __metaclass__ = PoolMeta
    __name__ = 'account.payment.journal'
    party = fields.Many2One('party.party', 'Party',
        help=('The party who sends the payment group, if it is different from '
        'the company.'))


class Group:
    __metaclass__ = PoolMeta
    __name__ = 'account.payment.group'
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


class Payment(BankMixin):
    __metaclass__ = PoolMeta
    __name__ = 'account.payment'
    payment_type = fields.Function(fields.Many2One('account.payment.type',
            'Payment Type'), 'on_change_with_payment_type')

    @classmethod
    def __setup__(cls):
        super(Payment, cls).__setup__()
        if 'payment_type' not in cls.journal.depends:
            cls.journal.depends.append('payment_type')
        cls._error_messages.update({
                'no_mandate_for_party': ('No valid mandate for payment '
                    '"%(payment)s" of party "%(party)s" with amount '
                    '"%(amount)s".'),
                })

    @fields.depends('journal')
    def on_change_with_payment_type(self, name=None):
        if self.journal:
            return self.journal.payment_type.id
        return None

    @fields.depends('party', 'journal', 'company', 'account_bank_from')
    def on_change_journal(self):
        self.payment_type = self.on_change_with_payment_type()
        self.account_bank = self.on_change_with_account_bank()
        self.account_bank_from = self.on_change_with_account_bank_from()
        self.bank_account = self.on_change_with_bank_account()

    @classmethod
    def get_sepa_mandates(cls, payments):
        mandates = super(Payment, cls).get_sepa_mandates(payments)
        mandates2 = []
        for payment, mandate in zip(payments, mandates):
            if not mandate:
                cls.raise_user_error('no_mandate_for_party', {
                        'payment': payment.rec_name,
                        'party': payment.party.rec_name,
                        'amount': payment.amount,
                        })
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


class PayLine:
    __metaclass__ = PoolMeta
    __name__ = 'account.move.line.pay'

    def get_payment(self, line, journals):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        payment = super(PayLine, self).get_payment(line, journals)
        if isinstance(line.origin, Invoice):
            payment.bank_account = line.origin.bank_account
        return payment
