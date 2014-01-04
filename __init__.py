# This file is part of account_bank module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from .account import *


def register():
    Pool.register(
        PaymentType,
        Invoice,
        Line,
        module='account_bank', type_='model')
