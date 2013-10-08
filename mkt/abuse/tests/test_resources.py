import json

from django.core import mail

from nose.tools import eq_

from abuse.models import AbuseReport
from mkt.abuse.resources import AppAbuseResource, UserAbuseResource
from mkt.account.tests.test_api import TestPotatoCaptcha
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.api.tests.test_throttle import ThrottleTests
from mkt.api.base import list_url
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from users.models import UserProfile


class BaseTestAbuseResource(ThrottleTests, TestPotatoCaptcha, BaseOAuth):
    """
    Setup for AbuseResource tests that require inheritance from TestCase.
    """
    resource_name = None

    def setUp(self):
        super(BaseTestAbuseResource, self).setUp(api_name='abuse')
        self.list_url = list_url(self.resource_name)
        self.headers = {
            'REMOTE_ADDR': '48.151.623.42'
        }


class AbuseResourceTests(object):
    """
    Setup for AbuseResource tests that do not require inheritance from
    TestCase.

    Separate from BaseTestAbuseResource to ensure that test_* methods of this
    abstract base class are not discovered by the runner.
    """
    default_data = None

    def _call(self, anonymous=False, data=None):
        post_data = self.default_data.copy()
        if data:
            post_data.update(data)

        client = self.anon if anonymous else self.client
        res = client.post(self.list_url, data=json.dumps(post_data),
                          **self.headers)
        try:
            res_data = json.loads(res.content)

        # Pending #855817, some errors will return an empty response body.
        except ValueError:
            res_data = res.content

        return res, res_data

    def _test_success(self, res, data):
        """
        Tests common when looking to ensure complete successful responses.
        """
        eq_(201, res.status_code)
        fields = self.default_data.copy()

        del fields['sprout']

        if 'user' in fields:
            eq_(data.pop('user')['display_name'], self.user.display_name)
            del fields['user']
        if 'app' in fields:
            eq_(int(data.pop('app')['id']), self.app.pk)
            del fields['app']

        for name in fields.keys():
            eq_(fields[name], data[name])

        newest_report = AbuseReport.objects.order_by('-id')[0]
        eq_(newest_report.message, data['text'])

        eq_(len(mail.outbox), 1)
        assert self.default_data['text'] in mail.outbox[0].body

    def test_send(self):
        res, data = self._call()
        self._test_success(res, data)
        assert 'display_name' in data['reporter']

    def test_send_anonymous(self):
        res, data = self._call(anonymous=True)
        self._test_success(res, data)
        eq_(data['reporter'], None)

    def test_send_potato(self):
        tuber_res, tuber_data = self._call(data={'tuber': 'potat-toh'},
                                           anonymous=True)
        potato_res, potato_data = self._call(data={'sprout': 'potat-toh'},
                                             anonymous=True)
        self._test_bad_api_potato_data(tuber_res, tuber_data)
        self._test_bad_api_potato_data(potato_res, potato_data)

    def test_send_bad_data(self):
        """
        One test to ensure that AbuseForm is running validation. We will rely
        on its tests for the rest.
        """
        res, data = self._call(data={'text': None})
        eq_(400, res.status_code)
        assert 'text' in data['error_message']


class TestUserAbuseResource(AbuseResourceTests, BaseTestAbuseResource):
    resource = UserAbuseResource()
    resource_name = 'user'

    def setUp(self):
        super(TestUserAbuseResource, self).setUp()
        self.user = UserProfile.objects.get(pk=2519)
        self.default_data = {
            'text': '@cvan is very abusive.',
            'sprout': 'potato',
            'user': self.user.pk
        }

    def test_invalid_user(self):
        res, data = self._call(data={'user': -1})
        eq_(400, res.status_code)
        assert 'user' in data['error_message']


class TestAppAbuseResource(AbuseResourceTests, BaseTestAbuseResource):
    fixtures = BaseTestAbuseResource.fixtures + fixture('webapp_337141')
    resource = AppAbuseResource()
    resource_name = 'app'

    def setUp(self):
        super(TestAppAbuseResource, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.default_data = {
            'text': "@cvan's app is very abusive.",
            'sprout': 'potato',
            'app': self.app.pk
        }

    def test_invalid_app(self):
        res, data = self._call(data={'app': -1})
        eq_(400, res.status_code)
        assert 'app' in data['error_message']

    def test_slug_app(self):
        res, data = self._call(data={'app': self.app.app_slug})
        eq_(201, res.status_code)
