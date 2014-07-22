#!/usr/bin/env python
# This file is part of account_bank module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.tests.test_tryton import test_view, test_depends, doctest_dropdb
import trytond.tests.test_tryton
import unittest
import doctest


class AccountBankTestCase(unittest.TestCase):
    'Test Account Bank module'

    def setUp(self):
        trytond.tests.test_tryton.install_module('account_bank')

    def test0005views(self):
        'Test views'
        test_view('account_bank')

    def test0006depends(self):
        'Test depends'
        test_depends()


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        AccountBankTestCase))
    suite.addTests(doctest.DocFileSuite('scenario_compensation_move.rst',
            setUp=doctest_dropdb, tearDown=doctest_dropdb, encoding='utf-8',
            optionflags=doctest.REPORT_ONLY_FIRST_FAILURE))
    return suite
