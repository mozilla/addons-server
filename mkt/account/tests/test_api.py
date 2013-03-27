import collections
import json
import uuid

from mock import patch
from nose.tools import eq_
import waffle

from django.conf import settings

from amo.tests import TestCase
from mkt.api.tests.test_oauth import BaseOAuth, get_absolute_url, OAuthClient
from mkt.api.base import list_url, get_url
from mkt.constants.apps import INSTALL_TYPE_REVIEWER
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed
from users.models import UserProfile


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestAccount(BaseOAuth):
    fixtures = fixture('user_2519', 'user_10482', 'webapp_337141')

    def setUp(self):
        super(TestAccount, self).setUp(api_name='account')
        self.list_url = list_url('settings')
        self.get_url = get_url('settings', '2519')
        self.anon = OAuthClient(None, api_name='account')
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
        eq_(data['installed'], [])

    def test_install(self):
        ins = Installed.objects.create(user=self.user, addon_id=337141)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['installed'],
            [get_absolute_url(get_url('app', ins.addon.pk), absolute=False)])

    def test_install_reviewer(self):
        Installed.objects.create(user=self.user, addon_id=337141,
                                 install_type=INSTALL_TYPE_REVIEWER)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['installed'], [])

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

browserid_url = 'http://firepla.ce:8675/'


class FakeUUID(object):
    hex = '000000'


@patch.object(settings, 'FIREPLACE_SECRET_KEY', 'gubbish')
@patch.object(settings, 'FIREPLACE_URL', browserid_url)
class TestLoginHandler(TestCase):
    def setUp(self):
        super(TestLoginHandler, self).setUp()
        self.list_url = get_absolute_url(list_url('login'), api_name='account')
        self.create_switch('browserid-login')

    @patch.object(uuid, 'uuid4', FakeUUID)
    @patch('requests.post')
    def test_login_success(self, http_request):
        FakeResponse = collections.namedtuple('FakeResponse',
                                              'status_code content')
        http_request.return_value = FakeResponse(200, json.dumps(
                {'status': 'okay',
                 'email': 'cvan@mozilla.com'}))
        res = self.client.post(self.list_url,
                               dict(assertion='fake-assertion',
                                    audience='fakeamo.org'))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['token'],
            'cvan@mozilla.com,95c9063d9f249aacfe5697fc83192ed6480c01463e2a80b3'
            '5af5ecaef11754700f4be33818d0e83a0cfc2cab365d60ba53b3c2b9f8f6589d1'
            'c43e9bbb876eef0,000000')

    @patch('requests.post')
    def test_login_failure(self, http_request):
        FakeResponse = collections.namedtuple('FakeResponse',
                                              'status_code content')
        http_request.return_value = FakeResponse(200, json.dumps(
                {'status': 'busted'}))
        res = self.client.post(self.list_url,
                               dict(assertion='fake-assertion',
                                    audience='fakeamo.org'))
        eq_(res.status_code, 401)
