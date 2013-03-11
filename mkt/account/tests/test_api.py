import json

from mock import patch
from nose.tools import eq_

from django.conf import settings

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
        super(TestAccount, self).setUp()
        self.list_url = list_url('account')
        self.get_url = get_url('account', '2519')
        self.anon = OAuthClient(None, api_name='apps')
        self.user = UserProfile.objects.get(pk=2519)

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ())
        self._allowed_verbs(self.get_url, ('get',))

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
        eq_(self.client.get(get_url('account', '10482')).status_code, 403)

    def test_own(self):
        res = self.client.get(get_url('account', 'mine'))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['display_name'], self.user.display_name)
