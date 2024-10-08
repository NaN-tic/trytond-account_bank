import datetime
import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear, create_tax,
                                                 get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        today = datetime.date.today()

        # Install account_bank Module
        config = activate_modules('account_bank')

        # Create company
        _ = create_company()
        company = get_company()

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        receivable = accounts['receivable']
        revenue = accounts['revenue']
        expense = accounts['expense']
        cash = accounts['cash']

        # Create tax
        tax = create_tax(Decimal('.10'))
        tax.save()

        # Create party
        Party = Model.get('party.party')
        party = Party(name='Party')
        party.save()

        # Create bank account
        Bank = Model.get('bank')
        BankAccount = Model.get('bank.account')
        bparty = Party()
        bparty.name = 'Bank'
        bparty.save()
        bank = Bank(party=bparty)
        bank.save()
        bank_account = BankAccount()
        bank_account.bank = bank
        bank_number = bank_account.numbers.new()
        bank_number.type = 'iban'
        bank_number.number = 'BE82068896274468'
        bank_number = bank_account.numbers.new()
        bank_number.type = 'other'
        bank_number.number = 'not IBAN'
        bank_account.save()
        party.bank_accounts.append(bank_account)
        party.save()

        # Create account category
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.customer_taxes.append(tax)
        account_category.save()

        # Create product
        ProductUom = Model.get('product.uom')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        ProductTemplate = Model.get('product.template')
        template = ProductTemplate()
        template.name = 'product'
        template.default_uom = unit
        template.type = 'service'
        template.list_price = Decimal('40')
        template.account_category = account_category
        product, = template.products
        product.cost_price = Decimal('25')
        template.save()
        product, = template.products

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create payment type and link to party
        PaymentType = Model.get('account.payment.type')
        payable_payment_type = PaymentType(name='Type', kind='payable')
        payable_payment_type.save()
        receivable_payment_type = PaymentType(name='Type', kind='receivable')
        receivable_payment_type.account_bank = 'party'
        receivable_payment_type.save()
        party.customer_payment_type = receivable_payment_type
        party.supplier_payment_type = payable_payment_type
        party.save()

        # Create invoice
        Invoice = Model.get('account.invoice')
        InvoiceLine = Model.get('account.invoice.line')
        invoice = Invoice()
        invoice.party = party
        invoice.payment_term = payment_term
        line = InvoiceLine()
        invoice.lines.append(line)
        line.product = product
        line.quantity = 5
        line.unit_price = Decimal(40)
        line = InvoiceLine()
        invoice.lines.append(line)
        line.account = revenue
        line.description = 'Test'
        line.quantity = 1
        line.unit_price = Decimal(20)
        self.assertEqual(invoice.untaxed_amount, Decimal('220.00'))
        self.assertEqual(invoice.tax_amount, Decimal('20.00'))
        self.assertEqual(invoice.total_amount, Decimal('240.00'))
        self.assertEqual(invoice.payment_type, receivable_payment_type)
        invoice.bank_account = bank_account
        invoice.save()
        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        self.assertEqual(invoice.amount_to_pay, Decimal(240))
        line1, line2, _, _ = invoice.move.lines
        self.assertEqual(line1.payment_type, receivable_payment_type)
        self.assertEqual(line1.bank_account, bank_account)
        self.assertEqual(line2.payment_type, None)
        self.assertEqual(line2.bank_account, None)

        # Create credit note
        Invoice = Model.get('account.invoice')
        InvoiceLine = Model.get('account.invoice.line')
        credit_note = Invoice()
        credit_note.type = 'out'
        credit_note.party = party
        credit_note.payment_term = payment_term
        credit_note.payment_type = payable_payment_type
        line = InvoiceLine()
        credit_note.lines.append(line)
        line.product = product
        line.quantity = -1
        line.unit_price = Decimal(40)
        self.assertEqual(credit_note.untaxed_amount, Decimal(-40))
        self.assertEqual(credit_note.tax_amount, Decimal(-4))
        self.assertEqual(credit_note.total_amount, Decimal(-44))
        credit_note.save()
        Invoice.post([credit_note.id], config.context)
        credit_note.reload()
        self.assertEqual(credit_note.state, 'posted')
        self.assertEqual(credit_note.amount_to_pay, Decimal(-44))

        # Partialy reconcile both lines
        MoveLine = Model.get('account.move.line')
        lines = MoveLine.find([('account', '=', receivable.id)])
        compensation_move = Wizard('account.move.compensation_move',
                                   models=lines)
        compensation_move.form.maturity_date = today
        compensation_move.form.account = receivable
        compensation_move.form.payment_type = receivable_payment_type
        compensation_move.form.bank_account = None
        compensation_move.execute('create_move')
        credit_note.reload()
        self.assertEqual(credit_note.amount_to_pay, Decimal('0'))
        invoice.reload()
        self.assertEqual(invoice.amount_to_pay, Decimal('0'))

        # Create a move that pays the pending amount
        Period = Model.get('account.period')
        Move = Model.get('account.move')
        move = Move()
        period, = Period.find([
            ('start_date', '<=', today),
            ('end_date', '>=', today),
            ('type', '=', 'standard'),
        ])
        move.period = period
        move.date = today
        move.journal = lines[0].move.journal
        line = move.lines.new()
        line.account = receivable
        line.credit = Decimal('196.0')
        line.debit = Decimal('0.0')
        line.party = party
        line = move.lines.new()
        line.account = cash
        line.debit = Decimal('196.0')
        line.credit = Decimal('0.0')
        move.click('post')
        invoice.reload()
        self.assertEqual(invoice.amount_to_pay, Decimal('0'))
        lines = MoveLine.find([('account', '=', receivable.id)])
        to_reconcile = [l for l in lines if not l.reconciliation]
        reconcile_lines = Wizard('account.move.reconcile_lines', to_reconcile)
        self.assertEqual(reconcile_lines.state, 'end')
        invoice.reload()
        self.assertEqual(invoice.amount_to_pay, Decimal('0'))
        self.assertEqual(invoice.state, 'paid')
