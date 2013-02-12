from nose.tools import eq_

from mkt.account.forms import FeedbackForm
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
