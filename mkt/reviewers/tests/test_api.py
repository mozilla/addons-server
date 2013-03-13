import json

from django.conf import settings
from django.core.cache import cache

from mock import patch
from nose.tools import eq_
from test_utils import RequestFactory

from mkt.api.tests.test_oauth import BaseOAuth, get_absolute_url, OAuthClient
from mkt.api.base import get_url, list_url
from mkt.reviewers.utils import AppsReviewing
from mkt.site.fixtures import fixture
from users.models import UserProfile


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestAccount(BaseOAuth):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestAccount, self).setUp(api_name='reviewers')
        self.list_url = list_url('reviewing')
        self.anon = OAuthClient(None, api_name='reviewers')
        self.user = UserProfile.objects.get(pk=2519)
        self.req = RequestFactory().get('/')
        self.req.amo_user = self.user

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ('get'))

    def test_not_allowed(self):
        eq_(self.anon.get(self.list_url).status_code, 401)

    def test_still_not_allowed(self):
        eq_(self.client.get(self.list_url).status_code, 401)

    def add_perms(self):
        self.grant_permission(self.user, 'Apps:Review')

    def test_allowed(self):
        self.add_perms()
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['objects'], [])

    def test_some(self):
        self.add_perms()

        # This feels rather brittle.
        cache.set('%s:review_viewing:%s' % (settings.CACHE_PREFIX, 337141),
                  2519, 50 * 2)
        AppsReviewing(self.req).add(337141)

        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['objects'][0]['resource_uri'],
            get_absolute_url(get_url('app', '337141'), absolute=False))
