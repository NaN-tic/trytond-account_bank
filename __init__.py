# This file is part of account_bank module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import account
from . import payment
from . import party


def register():
    Pool.register(
        account.PaymentType,
        account.BankAccount,
        account.Party,
        account.Invoice,
        account.Line,
        account.CompensationMoveStart,
        payment.Journal,
        payment.Group,
        payment.Payment,
        module='account_bank', type_='model')
    Pool.register(
        payment.PayLine,
        account.CompensationMove,
        party.PartyReplace,
        module='account_bank', type_='wizard')
