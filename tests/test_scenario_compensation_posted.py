import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.exceptions import UserError
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestCompensationPosted(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        # Without account_common, posted moves cannot be reset to draft.
        activate_modules('account_bank')
        create_company()
        company = get_company()
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')
        create_chart(company)
        accounts = get_accounts(company)
        Party = Model.get('party.party')
        party = Party(name='Customer')
        party.save()
        Move = Model.get('account.move')
        Journal = Model.get('account.journal')
        journal, = Journal.find([('type', '=', 'general')], limit=1)

        originals = []
        for amount in [Decimal('100'), Decimal('-40')]:
            move = Move(journal=journal)
            line = move.lines.new()
            line.account = accounts['receivable']
            line.party = party
            line.debit = max(amount, Decimal(0))
            line.credit = max(-amount, Decimal(0))
            counterpart = move.lines.new()
            counterpart.account = accounts['revenue']
            counterpart.debit = line.credit
            counterpart.credit = line.debit
            move.click('post')
            originals.append(next(l for l in move.lines
                    if l.account == accounts['receivable']))

        wizard = Wizard('account.move.compensation_move', models=originals)
        wizard.form.account = accounts['receivable']
        wizard.execute('create_move')
        compensation, = Move.find([('is_compensation', '=', True)])
        residual, = [l for l in compensation.lines if not l.reconciliation]
        self.assertEqual(residual.debit, Decimal('60'))
        for line in originals:
            line.reload()
        reconciliations = [l.reconciliation for l in originals]
        self.assertTrue(all(reconciliations))
        move_ids = {m.id for m in Move.find([])}

        with self.assertRaisesRegex(UserError, 'cannot be reset to draft'):
            Wizard('account.move.undo_compensation', models=[residual])
        compensation.reload()
        self.assertEqual(compensation.state, 'posted')
        self.assertEqual({m.id for m in Move.find([])}, move_ids)
        for line, reconciliation in zip(originals, reconciliations):
            line.reload()
            self.assertEqual(line.reconciliation, reconciliation)

        compensation.period.click('close')
        with self.assertRaisesRegex(UserError, 'period is not open'):
            Wizard('account.move.undo_compensation', models=[residual])
        self.assertEqual({m.id for m in Move.find([])}, move_ids)
        for line, reconciliation in zip(originals, reconciliations):
            line.reload()
            self.assertEqual(line.reconciliation, reconciliation)
