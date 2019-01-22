======================
Party Replace Scenario
======================

Imports::
    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import Model, Wizard
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts, create_tax
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()

Install account_bank Module::

    >>> config = activate_modules('account_bank')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> receivable = accounts['receivable']
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> cash = accounts['cash']

Create tax::

    >>> tax = create_tax(Decimal('.10'))
    >>> tax.save()

Create party::

    >>> Party = Model.get('party.party')
    >>> party = Party(name='Party')
    >>> party.save()

Create party2::

    >>> party2 = Party(name='Party')
    >>> party2.save()

Create bank account::

    >>> Bank = Model.get('bank')
    >>> BankAccount = Model.get('bank.account')
    >>> BankNumber = Model.get('bank.account.number')
    >>> bparty = Party()
    >>> bparty.name = 'Bank'
    >>> bparty.save()
    >>> bank = Bank(party=bparty)
    >>> bank.save()
    >>> bank_account = BankAccount()
    >>> bank_account.bank = bank
    >>> bank_number = bank_account.numbers.new()
    >>> bank_number.type = 'iban'
    >>> bank_number.number = 'BE82068896274468'
    >>> bank_number = bank_account.numbers.new()
    >>> bank_number.type = 'other'
    >>> bank_number.number = 'not IBAN'
    >>> bank_account.save()
    >>> party.bank_accounts.append(bank_account)
    >>> party.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> template = ProductTemplate()
    >>> template.name = 'product'
    >>> template.default_uom = unit
    >>> template.type = 'service'
    >>> template.list_price = Decimal('40')
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.customer_taxes.append(tax)
    >>> product, = template.products
    >>> product.cost_price = Decimal('25')
    >>> template.save()
    >>> product, = template.products

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create payment type and link to party::

    >>> PaymentType = Model.get('account.payment.type')
    >>> payment_type = PaymentType(name='Type', kind='both')
    >>> payment_type.account_bank='other'
    >>> payment_type.party = party
    >>> payment_type.bank_account = bank_account
    >>> payment_type.save()

Try replace active party::

    >>> replace = Wizard('party.replace', models=[party])
    >>> replace.form.source = party
    >>> replace.form.destination = party2
    >>> replace.execute('replace')

Check fields have been replaced::

    >>> payment_type.reload()
    >>> payment_type.party == party2
    True
