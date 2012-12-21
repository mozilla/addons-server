from nose.tools import eq_

import amo.tests
from mkt.lookup.forms import TransactionSearchForm


class TestTransactionSearchForm(amo.tests.TestCase):

    def test_basic(self):
        """Test the form doesn't crap out."""
        self.check_valid({'q': 12345}, True)

    def test_str_number(self):
        self.check_valid({'q': '12345'})

    def test_not_number(self):
        self.check_valid({'q': 'ekong'}, valid=False)

    def check_valid(self, data, valid=True):
        form = TransactionSearchForm(data)
        eq_(form.is_valid(), valid)
