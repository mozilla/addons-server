from nose.tools import eq_

from amo.tests import TestCase
from mkt.account.forms import LoginForm


class TestLoginForm(TestCase):
    def setUp(self):
        self.data = {
            'assertion': 'fake',
            'audience': 'example.com'
        }

    def test_success(self):
        form = LoginForm(self.data)
        eq_(form.is_valid(), True)

    def test_empty(self):
        form = LoginForm({})
        eq_(form.is_valid(), False)

    def test_no_assertion(self):
        del self.data['assertion']
        form = LoginForm(self.data)
        eq_(form.is_valid(), False)

    def test_no_audience(self):
        del self.data['audience']
        form = LoginForm(self.data)
        eq_(form.is_valid(), True)
