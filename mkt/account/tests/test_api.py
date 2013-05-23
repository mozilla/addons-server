import collections
import json
import uuid

from django.conf import settings
from django.core import mail

from mock import patch
from nose.tools import eq_, ok_

from amo.tests import TestCase
from mkt.account.api import FeedbackResource
from mkt.api.base import get_url, list_url
from mkt.api.tests.test_oauth import BaseOAuth, get_absolute_url
from mkt.api.tests.test_throttle import ThrottleTests
from mkt.constants.apps import INSTALL_TYPE_REVIEWER
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed
from users.models import UserProfile


class TestPotatoCaptcha(object):

    def _test_bad_api_potato_data(self, response, data=None):
        if not data:
            data = json.loads(response.content)
        eq_(400, response.status_code)
        assert '__all__' in data['error_message']


class TestPermission(BaseOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestPermission, self).setUp(api_name='account')
        self.get_url = get_url('permissions', '2519')
        self.user = UserProfile.objects.get(pk=2519)

    def test_verbs(self):
        self._allowed_verbs(self.get_url, ('get'))

    def test_no_permissions(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        self.assertSetEqual(
            ['admin', 'developer', 'reviewer', 'localizer', 'lookup',
             'webpay'],
            res.json['permissions'].keys()
        )
        ok_(not all(res.json['permissions'].values()))

    def test_some_permission(self):
        self.grant_permission(self.user, 'Localizers:%')
        res = self.client.get(self.get_url)
        ok_(res.json['permissions']['localizer'])

    def test_webpay(self):
        res = self.client.get(self.get_url)
        ok_(not res.json['permissions']['webpay'])

    def test_webpay_ok(self):
        self.grant_permission(self.user, 'ProductIcon:Create')
        self.grant_permission(self.user, 'Transaction:NotifyFailure')
        res = self.client.get(self.get_url)
        ok_(res.json['permissions']['webpay'])


class TestAccount(BaseOAuth):
    fixtures = fixture('user_2519', 'user_10482', 'webapp_337141')

    def setUp(self):
        super(TestAccount, self).setUp(api_name='account')
        self.list_url = list_url('settings')
        self.get_url = get_url('settings', '2519')
        self.user = UserProfile.objects.get(pk=2519)

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ())
        self._allowed_verbs(self.get_url, ('get', 'patch', 'put'))

    def test_not_allowed(self):
        eq_(self.anon.get(self.get_url).status_code, 401)

    def test_allowed(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['display_name'], self.user.display_name)

    def test_other(self):
        eq_(self.client.get(get_url('settings', '10482')).status_code, 403)

    def test_own(self):
        res = self.client.get(get_url('settings', 'mine'))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['display_name'], self.user.display_name)

    def test_patch(self):
        res = self.client.patch(self.get_url,
                                data=json.dumps({'display_name': 'foo'}))
        eq_(res.status_code, 202)
        user = UserProfile.objects.get(pk=self.user.pk)
        eq_(user.display_name, 'foo')

    def test_put(self):
        res = self.client.put(self.get_url,
                              data=json.dumps({'display_name': 'foo'}))
        eq_(res.status_code, 204)
        user = UserProfile.objects.get(pk=self.user.pk)
        eq_(user.display_name, 'foo')
        eq_(user.username, self.user.username)  # Did not change.

    def test_patch_extra_fields(self):
        res = self.client.patch(self.get_url,
                                data=json.dumps({'display_name': 'foo',
                                                 'username': 'bob'}))
        eq_(res.status_code, 202)
        user = UserProfile.objects.get(pk=self.user.pk)
        eq_(user.display_name, 'foo')  # Got changed successfully.
        eq_(user.username, self.user.username)  # Did not change.

    def test_patch_other(self):
        res = self.client.patch(get_url('settings', '10482'),
                                data=json.dumps({'display_name': 'foo'}))
        eq_(res.status_code, 403)


class TestInstalled(BaseOAuth):
    fixtures = fixture('user_2519', 'user_10482', 'webapp_337141')

    def setUp(self):
        super(TestInstalled, self).setUp(api_name='account')
        self.list_url = list_url('installed/mine')
        self.user = UserProfile.objects.get(pk=2519)

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ('get'))

    def test_not_allowed(self):
        eq_(self.anon.get(self.list_url).status_code, 401)

    def test_installed(self):
        ins = Installed.objects.create(user=self.user, addon_id=337141)
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['id'], str(ins.addon.pk))

    def not_there(self):
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 0)

    def test_installed_other(self):
        Installed.objects.create(user_id=10482, addon_id=337141)
        self.not_there()

    def test_installed_reviewer(self):
        Installed.objects.create(user=self.user, addon_id=337141,
                                 install_type=INSTALL_TYPE_REVIEWER)
        self.not_there()


class FakeUUID(object):
    hex = '000000'


@patch.object(settings, 'SECRET_KEY', 'gubbish')
class TestLoginHandler(TestCase):

    def setUp(self):
        super(TestLoginHandler, self).setUp()
        self.list_url = get_absolute_url(list_url('login'), api_name='account')

    def post(self, data):
        return self.client.post(self.list_url, json.dumps(data),
                                content_type='application/json')

    @patch.object(uuid, 'uuid4', FakeUUID)
    @patch('requests.post')
    def _test_login(self, http_request):
        FakeResponse = collections.namedtuple('FakeResponse',
                                              'status_code content')
        http_request.return_value = FakeResponse(200, json.dumps(
                {'status': 'okay',
                 'email': 'cvan@mozilla.com'}))
        res = self.post({'assertion': 'fake-assertion',
                         'audience': 'fakeamo.org'})
        eq_(res.status_code, 201)
        data = json.loads(res.content)
        eq_(data['token'],
            'cvan@mozilla.com,95c9063d9f249aacfe5697fc83192ed6480c01463e2a80b3'
            '5af5ecaef11754700f4be33818d0e83a0cfc2cab365d60ba53b3c2b9f8f6589d1'
            'c43e9bbb876eef0,000000')

        return data

    def test_login_new_user_success(self):
        data = self._test_login()
        ok_(not any(data['permissions'].values()))

    def test_login_existing_user_success(self):
        profile = UserProfile.objects.create(email='cvan@mozilla.com')
        profile.create_django_user(
            backend='django_browserid.auth.BrowserIDBackend')
        self.grant_permission(profile, 'Apps:Review')

        data = self._test_login()
        eq_(data['permissions'],
            {'admin': False,
             'localizer': False,
             'lookup': False,
             'webpay': False,
             'reviewer': True,
             'developer': False})

    @patch('requests.post')
    def test_login_failure(self, http_request):
        FakeResponse = collections.namedtuple('FakeResponse',
                                              'status_code content')
        http_request.return_value = FakeResponse(200, json.dumps(
                {'status': 'busted'}))
        res = self.post({'assertion': 'fake-assertion',
                         'audience': 'fakeamo.org'})
        eq_(res.status_code, 401)

    def test_login_empty(self):
        res = self.post({})
        data = json.loads(res.content)
        eq_(res.status_code, 400)
        assert 'assertion' in data['error_message']


class TestFeedbackHandler(ThrottleTests, TestPotatoCaptcha, BaseOAuth):
    resource = FeedbackResource()

    def setUp(self):
        super(TestFeedbackHandler, self).setUp(api_name='account')
        self.list_url = list_url('feedback')
        self.user = UserProfile.objects.get(pk=2519)
        self.default_data = {
            'chromeless': 'no',
            'feedback': 'Here is what I really think.',
            'platform': 'Desktop',
            'from_url': '/feedback',
            'sprout': 'potato'
        }
        self.headers = {
            'HTTP_USER_AGENT': 'Fiiia-fox',
            'REMOTE_ADDR': '48.151.623.42'
        }

    def _call(self, anonymous=False, data=None):
        post_data = self.default_data.copy()
        client = self.anon if anonymous else self.client
        if data:
            post_data.update(data)
        res = client.post(self.list_url, data=json.dumps(post_data),
                          **self.headers)
        try:
            res_data = json.loads(res.content)

        # Pending #855817, some errors will return an empty response body.
        except ValueError:
            res_data = res.content
        return res, res_data

    def _test_success(self, res, data):
        eq_(201, res.status_code)

        fields = self.default_data.copy()
        del fields['sprout']
        for name in fields.keys():
            eq_(fields[name], data[name])

        eq_(len(mail.outbox), 1)
        assert self.default_data['feedback'] in mail.outbox[0].body
        assert self.headers['REMOTE_ADDR'] in mail.outbox[0].body

    def test_send(self):
        res, data = self._call()
        self._test_success(res, data)
        eq_(unicode(self.user), data['user'])
        eq_(mail.outbox[0].from_email, self.user.email)

    def test_send_without_platform(self):
        del self.default_data['platform']
        self.list_url += ({'dev': 'platfoo'}, )

        res, data = self._call()
        self._test_success(res, data)
        assert 'platfoo' in mail.outbox[0].body

    def test_send_anonymous(self):
        res, data = self._call(anonymous=True)
        self._test_success(res, data)
        assert not data['user']
        eq_(settings.NOBODY_EMAIL, mail.outbox[0].from_email)

    def test_send_potato(self):
        tuber_res, tuber_data = self._call(data={'tuber': 'potat-toh'},
                                           anonymous=True)
        potato_res, potato_data = self._call(data={'sprout': 'potat-toh'},
                                             anonymous=True)
        self._test_bad_api_potato_data(tuber_res, tuber_data)
        self._test_bad_api_potato_data(potato_res, potato_data)

    def test_missing_optional_field(self):
        res, data = self._call(data={'platform': None})
        eq_(201, res.status_code)

    def test_send_bad_data(self):
        """
        One test to ensure that FeedbackForm is doing its validation duties.
        We'll rely on FeedbackForm tests for the rest.
        """
        res, data = self._call(data={'feedback': None})
        eq_(400, res.status_code)
        assert 'feedback' in data['error_message']


class TestNewsletter(BaseOAuth):
    def setUp(self):
        super(TestNewsletter, self).setUp(api_name='account')

    @patch('basket.subscribe')
    def test_signup(self, subscribe):
        res = self.client.post(list_url('newsletter'))
        eq_(res.status_code, 400)
        res = self.client.post(list_url('newsletter'),
                               data=json.dumps({'email': 'bob@example.com'}))
        eq_(res.status_code, 204)
        subscribe.assert_called_with(
            'bob@example.com', 'marketplace', lang='en-US', country='us',
            trigger_welcome='Y', optin='Y', format='H')

