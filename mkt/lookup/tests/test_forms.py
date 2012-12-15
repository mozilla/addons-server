from nose.tools import eq_

import amo.tests
from mkt.lookup.forms import TransactionSearchForm


class TestTransactionSearchForm(amo.tests.TestCase):

    def setUp(self):
        self.data = {'q': 12345}

    def test_basic(self):
        """Test the form doesn't crap out."""
        self.check_valid(True)

    def test_str_number(self):
        self.data['q'] = '12345'
        self.check_valid(True)

    def test_not_number(self):
        self.data['q'] = 'ekong'
        self.check_valid(False)

    def check_valid(self, valid):
        form = TransactionSearchForm(self.data)
        eq_(form.is_valid(), valid)
