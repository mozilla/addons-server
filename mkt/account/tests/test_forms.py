from nose.tools import eq_

from amo.tests import TestCase
from mkt.account.forms import FeedbackForm, LoginForm
from mkt.site.tests.test_forms import PotatoCaptchaTestCase


class TestFeedbackForm(PotatoCaptchaTestCase):

    def test_success(self):
        self.data['feedback'] = 'yolo'
        form = FeedbackForm(self.data, request=self.request)
        eq_(form.is_valid(), True)

    def test_error_feedback_required(self):
        form = FeedbackForm(self.data, request=self.request)
        eq_(form.is_valid(), False)
        eq_(form.errors, {'feedback': [u'This field is required.']})


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
