# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import fields
from trytond.pool import Pool, PoolMeta

__all__ = ['Party', 'PartyDefaultBankAccount']


class Party:
    __metaclass__ = PoolMeta
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


class PartyDefaultBankAccount:
    __metaclass__ = PoolMeta
    __name__ = 'party.party.default.bank_account'

    payment_type = fields.Many2One('account.payment.type', 'Payment Type',
        domain=[
            ('account_bank', '!=', 'none'),
            ])

    @fields.depends('party', 'company', 'payment_type')
    def on_change_with_bank_account_owner(self, name=None):
        party = super(PartyDefaultBankAccount,
            self).on_change_with_bank_account_owner(name)
        if not self.payment_type or self.payment_type.account_bank == 'party':
            return party
        if self.payment_type.account_bank == 'company':
            return self.company.party.id if self.company else None
        if self.payment_type.account_bank == 'other':
            return self.payment_type.party.id
