from nose.tools import eq_

import amo.tests
from amo.urlresolvers import reverse
from users.models import UserProfile

from mkt.api.models import Access
from mkt.site.fixtures import fixture


class TestAPI(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        self.profile = UserProfile.objects.get(pk=999)
        self.user = self.profile.user
        self.login(self.profile)
        self.url = reverse('mkt.developers.apps.api')

    def test_logged_out(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_non_url(self):
        res = self.client.post(
            self.url,
            {'app_name': 'test', 'redirect_uri': 'mailto:cvan@example.com'})
        self.assertFormError(res, 'form', 'redirect_uri', ['Enter a valid URL.'])

    def test_create(self):
        Access.objects.create(user=self.user, key='foo', secret='bar')
        res = self.client.post(
            self.url,
            {'app_name': 'test', 'redirect_uri': 'https://example.com/myapp'})
        self.assertNoFormErrors(res)
        eq_(res.status_code, 200)
        consumers = Access.objects.filter(user=self.user)
        eq_(len(consumers), 2)
        eq_(consumers[1].key, 'mkt:999:regular@mozilla.com:1')

    def test_delete(self):
        a = Access.objects.create(user=self.user, key='foo', secret='bar')
        res = self.client.post(self.url, {'delete': 'yep', 'consumer': a.pk})
        eq_(res.status_code, 200)
        eq_(Access.objects.filter(user=self.user).count(), 0)

    def test_admin(self):
        self.grant_permission(self.profile, 'What:ever', name='Admins')
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(Access.objects.filter(user=self.user).count(), 0)

    def test_other(self):
        self.grant_permission(self.profile, 'What:ever')
        res = self.client.post(
            self.url,
            {'app_name': 'test', 'redirect_uri': 'http://example.com/myapp'})
        eq_(res.status_code, 200)
        eq_(Access.objects.filter(user=self.user).count(), 1)
