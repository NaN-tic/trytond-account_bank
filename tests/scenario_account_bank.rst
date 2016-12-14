=====================
Account Bank Scenario
=====================

Imports::

    >>> from proteus import Model, Wizard
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences

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

Create party::

    >>> Party = Model.get('party.party')
    >>> party = Party(name='Party')
    >>> party.save()

Create bank accounts::

    >>> Bank = Model.get('bank')
    >>> BankAccount = Model.get('bank.account')
    >>> bank_party = Party(name='Bank')
    >>> bank_party.save()
    >>> bank = Bank(party=bank_party)
    >>> bank.save()
    >>> company_account = BankAccount()
    >>> company_account.bank = bank
    >>> company_account.owners.append(company.party)
    >>> number = company_account.numbers.new()
    >>> number.type = 'other'
    >>> number.number = 'Company Account Number'
    >>> company_account.save()
    >>> party_account = BankAccount()
    >>> party_account.bank = bank
    >>> party_account.owners.append(party)
    >>> number = party_account.numbers.new()
    >>> number.type = 'other'
    >>> number.number = 'Party Account Number'
    >>> party_account.save()

Create payment types::

    >>> PaymentType = Model.get('account.payment.type')
    >>> cash = PaymentType(name='Cash', account_bank='none')
    >>> cash.save()
    >>> customer_transfer = PaymentType(name='Customer Transfer',
    ...     account_bank='party')
    >>> customer_transfer.save()
    >>> other_customer_transfer = PaymentType(name='Other Customer Transfer',
    ...     account_bank='party')
    >>> other_customer_transfer.save()
    >>> company_transfer = PaymentType(name='Company Transfer',
    ...     account_bank='company')
    >>> company_transfer.save()
    >>> other_company_transfer = PaymentType(name='Other Company Transfer',
    ...     account_bank='company')
    >>> other_company_transfer.save()

Check bank account is set when setting the party and payment_type::

    >>> Invoice = Model.get('account.invoice')
    >>> invoice = Invoice()
    >>> invoice.party = party
    >>> invoice.payment_type = customer_transfer
    >>> invoice.bank_account == party_account
    True

If we use a payment type with no bank account the bank_account is set to None::

    >>> invoice.payment_type = cash
    >>> invoice.bank_account

And setting the previous payment_type updates the bank_account::

    >>> invoice.payment_type = customer_transfer
    >>> invoice.bank_account == party_account
    True

The company bank account is used when the payment type requires it::

    >>> invoice.payment_type = company_transfer
    >>> invoice.bank_account == company_account
    True

If the party has several bank accounts no one is picked by default::

    >>> second_party_account = BankAccount()
    >>> second_party_account.bank = bank
    >>> second_party_account.owners.append(Party(party.id))
    >>> number = second_party_account.numbers.new()
    >>> number.type = 'other'
    >>> number.number = 'Second Party Account Number'
    >>> second_party_account.save()
    >>> invoice = Invoice()
    >>> invoice.party = party
    >>> invoice.payment_type = customer_transfer
    >>> invoice.bank_account

Unless we specify a default one for the party::

    >>> default_bank_account = party.default_bank_accounts.new()
    >>> default_bank_account.sequence = 10
    >>> default_bank_account.bank_account = second_party_account
    >>> default_bank_account.save()
    >>> invoice = Invoice()
    >>> invoice.party = party
    >>> invoice.payment_type = customer_transfer
    >>> invoice.bank_account == second_party_account
    True

We can define the bank account per payment_type::

    >>> default_bank_account = party.default_bank_accounts.new()
    >>> default_bank_account.sequence = 5
    >>> default_bank_account.payment_type = other_customer_transfer
    >>> default_bank_account.bank_account = party_account
    >>> default_bank_account.save()
    >>> invoice = Invoice()
    >>> invoice.party = party
    >>> invoice.payment_type = other_customer_transfer
    >>> invoice.bank_account == party_account
    True
    >>> invoice.payment_type = customer_transfer
    >>> invoice.bank_account == second_party_account
    True

And also the company bank account for company payment types::

    >>> second_company_account = BankAccount()
    >>> second_company_account.bank = bank
    >>> second_company_account.owners.append(Party(company.party.id))
    >>> number = second_company_account.numbers.new()
    >>> number.type = 'other'
    >>> number.number = 'Second Company Account Number'
    >>> second_company_account.save()
    >>> default_bank_account = company.party.default_bank_accounts.new()
    >>> default_bank_account.sequence = 5
    >>> default_bank_account.bank_account = company_account
    >>> default_bank_account.save()
    >>> default_bank_account = party.default_bank_accounts.new()
    >>> default_bank_account.sequence = 5
    >>> default_bank_account.payment_type = other_company_transfer
    >>> default_bank_account.bank_account = second_company_account
    >>> default_bank_account.save()
    >>> invoice = Invoice()
    >>> invoice.party = party
    >>> invoice.payment_type = company_transfer
    >>> invoice.bank_account == company_account
    True
    >>> invoice.payment_type = other_company_transfer
    >>> invoice.bank_account == second_company_account
    True

Create payment journal for customer transfer::

    >>> payment_journal = customer_transfer.journals.new()
    >>> payment_journal.name = 'Manual'
    >>> payment_journal.process_method = 'manual'
    >>> payment_journal.save()

The default bank accounts are used on payments also::

    >>> Payment = Model.get('account.payment')
    >>> payment = Payment()
    >>> payment.journal = payment_journal
    >>> payment.party = party
    >>> payment.bank_account == second_party_account
    True
