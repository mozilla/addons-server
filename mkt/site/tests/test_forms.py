from django.contrib.auth.models import User

import mock
from nose.tools import eq_

import amo.tests

from mkt.site.fixtures import fixture
from mkt.site.forms import AbuseForm, PotatoCaptchaForm


class PotatoCaptchaTestCase(amo.tests.TestCase):

    def setUp(self):
        self.request = mock.Mock()
        self.request.META = {}
        self.request.user = mock.Mock()
        self.context = {'request': self.request}
        self.request.user.is_authenticated = lambda: False
        self.data = {'tuber': '', 'sprout': 'potato'}


class TestPotatoCaptchaForm(PotatoCaptchaTestCase):
    fixtures = fixture('user_999')

    def test_success_authenticated(self):
        self.request.user = User.objects.get(id=999)
        self.request.user.is_authenticated = lambda: True
        form = PotatoCaptchaForm({}, request=self.request)
        eq_(form.is_valid(), True)

    def test_success_anonymous(self):
        data = {'tuber': '', 'sprout': 'potato'}
        form = PotatoCaptchaForm(data, request=self.request)
        eq_(form.is_valid(), True)

    def test_error_anonymous_bad_tuber(self):
        data = {'tuber': 'HAMMMMMMMMMMMMM', 'sprout': 'potato'}
        form = PotatoCaptchaForm(data, request=self.request)
        eq_(form.is_valid(), False)

    def test_error_anonymous_bad_sprout(self):
        data = {'tuber': 'HAMMMMMMMMMMMMM', 'sprout': ''}
        form = PotatoCaptchaForm(data, request=self.request)
        eq_(form.is_valid(), False)

    def test_error_anonymous_bad_tuber_and_sprout(self):
        form = PotatoCaptchaForm({}, request=self.request)
        eq_(form.is_valid(), False)


class TestAbuseForm(PotatoCaptchaTestCase):

    def setUp(self):
        self.request = mock.Mock()
        self.data = {'tuber': '', 'sprout': 'potato', 'text': 'test'}

    def test_success(self):
        form = AbuseForm(self.data, request=self.request)
        eq_(form.is_valid(), True)

    def test_error_text_required(self):
        self.data['text'] = ''
        form = AbuseForm(self.data, request=self.request)
        eq_(form.is_valid(), False)
        eq_(form.errors, {'text': [u'This field is required.']})
