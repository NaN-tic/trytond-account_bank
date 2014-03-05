================
Invoice Scenario
================

Imports::
    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from operator import attrgetter
    >>> from proteus import config, Model, Wizard
    >>> today = datetime.date.today()

Create database::

    >>> config = config.set_trytond()
    >>> config.pool.test = True

Install account_invoice::

    >>> Module = Model.get('ir.module.module')
    >>> account_invoice_module, = Module.find(
    ...     [('name', '=', 'account_bank')])
    >>> Module.install([account_invoice_module.id], config.context)
    >>> Wizard('ir.module.module.install_upgrade').execute('upgrade')

Create company::

    >>> Currency = Model.get('currency.currency')
    >>> CurrencyRate = Model.get('currency.currency.rate')
    >>> currencies = Currency.find([('code', '=', 'USD')])
    >>> if not currencies:
    ...     currency = Currency(name='US Dollar', symbol=u'$', code='USD',
    ...         rounding=Decimal('0.01'), mon_grouping='[]',
    ...         mon_decimal_point='.')
    ...     currency.save()
    ...     CurrencyRate(date=today + relativedelta(month=1, day=1),
    ...         rate=Decimal('1.0'), currency=currency).save()
    ... else:
    ...     currency, = currencies
    >>> Company = Model.get('company.company')
    >>> Party = Model.get('party.party')
    >>> company_config = Wizard('company.company.config')
    >>> company_config.execute('company')
    >>> company = company_config.form
    >>> party = Party(name='Dunder Mifflin')
    >>> party.save()
    >>> company.party = party
    >>> company.currency = currency
    >>> company_config.execute('add')
    >>> company, = Company.find([])

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> FiscalYear = Model.get('account.fiscalyear')
    >>> Sequence = Model.get('ir.sequence')
    >>> SequenceStrict = Model.get('ir.sequence.strict')
    >>> fiscalyear = FiscalYear(name=str(today.year))
    >>> fiscalyear.start_date = today + relativedelta(month=1, day=1)
    >>> fiscalyear.end_date = today + relativedelta(month=12, day=31)
    >>> fiscalyear.company = company
    >>> post_move_seq = Sequence(name=str(today.year), code='account.move',
    ...     company=company)
    >>> post_move_seq.save()
    >>> fiscalyear.post_move_sequence = post_move_seq
    >>> invoice_seq = SequenceStrict(name=str(today.year),
    ...     code='account.invoice', company=company)
    >>> invoice_seq.save()
    >>> fiscalyear.out_invoice_sequence = invoice_seq
    >>> fiscalyear.in_invoice_sequence = invoice_seq
    >>> fiscalyear.out_credit_note_sequence = invoice_seq
    >>> fiscalyear.in_credit_note_sequence = invoice_seq
    >>> fiscalyear.save()
    >>> FiscalYear.create_period([fiscalyear.id], config.context)

Create chart of accounts::

    >>> AccountTemplate = Model.get('account.account.template')
    >>> Account = Model.get('account.account')
    >>> account_template, = AccountTemplate.find([('parent', '=', None)])
    >>> create_chart = Wizard('account.create_chart')
    >>> create_chart.execute('account')
    >>> create_chart.form.account_template = account_template
    >>> create_chart.form.company = company
    >>> create_chart.execute('create_account')
    >>> receivable, = Account.find([
    ...         ('kind', '=', 'receivable'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> payable, = Account.find([
    ...         ('kind', '=', 'payable'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> revenue, = Account.find([
    ...         ('kind', '=', 'revenue'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> expense, = Account.find([
    ...         ('kind', '=', 'expense'),
    ...         ('company', '=', company.id),
    ...         ])
    >>> account_tax, = Account.find([
    ...         ('kind', '=', 'other'),
    ...         ('company', '=', company.id),
    ...         ('name', '=', 'Main Tax'),
    ...         ])
    >>> account_cash, = Account.find([
    ...         ('kind', '=', 'other'),
    ...         ('company', '=', company.id),
    ...         ('name', '=', 'Main Cash'),
    ...         ])
    >>> create_chart.form.account_receivable = receivable
    >>> create_chart.form.account_payable = payable
    >>> create_chart.execute('create_properties')

Create tax::

    >>> TaxCode = Model.get('account.tax.code')
    >>> Tax = Model.get('account.tax')
    >>> tax = Tax()
    >>> tax.name = 'Tax'
    >>> tax.description = 'Tax'
    >>> tax.type = 'percentage'
    >>> tax.rate = Decimal('.10')
    >>> tax.invoice_account = account_tax
    >>> tax.credit_note_account = account_tax
    >>> invoice_base_code = TaxCode(name='invoice base')
    >>> invoice_base_code.save()
    >>> tax.invoice_base_code = invoice_base_code
    >>> invoice_tax_code = TaxCode(name='invoice tax')
    >>> invoice_tax_code.save()
    >>> tax.invoice_tax_code = invoice_tax_code
    >>> credit_note_base_code = TaxCode(name='credit note base')
    >>> credit_note_base_code.save()
    >>> tax.credit_note_base_code = credit_note_base_code
    >>> credit_note_tax_code = TaxCode(name='credit note tax')
    >>> credit_note_tax_code.save()
    >>> tax.credit_note_tax_code = credit_note_tax_code
    >>> tax.save()

Create party::

    >>> Party = Model.get('party.party')
    >>> party = Party(name='Party')
    >>> party.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> ProductTemplate = Model.get('product.template')
    >>> Product = Model.get('product.product')
    >>> product = Product()
    >>> template = ProductTemplate()
    >>> template.name = 'product'
    >>> template.default_uom = unit
    >>> template.type = 'service'
    >>> template.list_price = Decimal('40')
    >>> template.cost_price = Decimal('25')
    >>> template.account_expense = expense
    >>> template.account_revenue = revenue
    >>> template.customer_taxes.append(tax)
    >>> template.save()
    >>> product.template = template
    >>> product.save()

Create payment term::

    >>> PaymentTerm = Model.get('account.invoice.payment_term')
    >>> PaymentTermLine = Model.get('account.invoice.payment_term.line')
    >>> payment_term = PaymentTerm(name='Term')
    >>> payment_term_line = PaymentTermLine(type='percent', days=20,
    ...     percentage=Decimal(50))
    >>> payment_term.lines.append(payment_term_line)
    >>> payment_term_line = PaymentTermLine(type='remainder', days=40)
    >>> payment_term.lines.append(payment_term_line)
    >>> payment_term.save()

Create payment type and link to party::

    >>> PaymentType = Model.get('account.payment.type')
    >>> payable_payment_type = PaymentType(name='Type', kind='payable')
    >>> payable_payment_type.save()
    >>> receivable_payment_type = PaymentType(name='Type', kind='receivable')
    >>> receivable_payment_type.save()
    >>> party.customer_payment_type = receivable_payment_type
    >>> party.supplier_payment_type = payable_payment_type
    >>> party.save()

Create invoice::

    >>> Invoice = Model.get('account.invoice')
    >>> InvoiceLine = Model.get('account.invoice.line')
    >>> invoice = Invoice()
    >>> invoice.party = party
    >>> invoice.payment_term = payment_term
    >>> line = InvoiceLine()
    >>> invoice.lines.append(line)
    >>> line.product = product
    >>> line.quantity = 5
    >>> line = InvoiceLine()
    >>> invoice.lines.append(line)
    >>> line.account = revenue
    >>> line.description = 'Test'
    >>> line.quantity = 1
    >>> line.unit_price = Decimal(20)
    >>> invoice.untaxed_amount == Decimal(220)
    True
    >>> invoice.tax_amount == Decimal(20)
    True
    >>> invoice.total_amount == Decimal(240)
    True
    >>> invoice.payment_type == receivable_payment_type
    True
    >>> invoice.save()
    >>> Invoice.post([invoice.id], config.context)
    >>> invoice.reload()
    >>> invoice.state
    u'posted'
    >>> invoice.amount_to_pay == Decimal(240)
    True

Create credit note::

    >>> Invoice = Model.get('account.invoice')
    >>> InvoiceLine = Model.get('account.invoice.line')
    >>> credit_note = Invoice()
    >>> credit_note.type = 'out_credit_note'
    >>> credit_note.party = party
    >>> credit_note.payment_term = payment_term
    >>> line = InvoiceLine()
    >>> credit_note.lines.append(line)
    >>> line.product = product
    >>> line.quantity = 1
    >>> credit_note.untaxed_amount == Decimal(40)
    True
    >>> credit_note.tax_amount == Decimal(4)
    True
    >>> credit_note.total_amount == Decimal(44)
    True
    >>> credit_note.save()
    >>> Invoice.post([credit_note.id], config.context)
    >>> credit_note.reload()
    >>> credit_note.state
    u'posted'
    >>> credit_note.amount_to_pay == Decimal(44)
    True


Partialy reconcile both lines::

    >>> MoveLine = Model.get('account.move.line')
    >>> lines = MoveLine.find([
    ...     ('account', '=', receivable.id)])
    >>> partial_reconcile = Wizard('account.move.partial_reconcile',
    ...     models=lines)
    >>> partial_reconcile.form.maturity_date = today
    >>> partial_reconcile.form.payment_type = receivable_payment_type
    >>> partial_reconcile.form.bank_account = None
    >>> partial_reconcile.execute('reconcile')
    >>> credit_note.reload()
    >>> credit_note.amount_to_pay == Decimal('0.0')
    True
    >>> invoice.reload()
    >>> invoice.amount_to_pay == Decimal('196.0')
    True


Create a move that pays the pending amount::

    >>> Period = Model.get('account.period')
    >>> Move = Model.get('account.move')
    >>> move = Move()
    >>> period, = Period.find([
    ...     ('start_date', '<=', today),
    ...     ('end_date', '>=', today),
    ...     ('type', '=', 'standard'),
    ...     ])
    >>> move.period = period
    >>> move.date = today
    >>> move.journal = lines[0].move.journal
    >>> line = MoveLine()
    >>> move.lines.append(line)
    >>> line.account = receivable
    >>> line.credit = Decimal('196.0')
    >>> line.debit = Decimal('0.0')
    >>> line.party = party
    >>> line = MoveLine()
    >>> move.lines.append(line)
    >>> line.account = account_cash
    >>> line.debit = Decimal('196.0')
    >>> line.credit = Decimal('0.0')
    >>> line.party = party
    >>> move.save()
    >>> Move.post([move.id], config.context)
    >>> invoice.reload()
    >>> invoice.amount_to_pay == Decimal('196.0')
    True
    >>> lines = MoveLine.find([
    ...     ('account', '=', receivable.id)])
    >>> to_reconcile = [l for l in lines if not l.reconciliation]
    >>> reconcile_lines = Wizard('account.move.reconcile_lines',
    ...     to_reconcile)
    >>> reconcile_lines.state == 'end'
    True
    >>> invoice.reload()
    >>> invoice.amount_to_pay == Decimal('0.0')
    True
    >>> invoice.state
    u'paid'
