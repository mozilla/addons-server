from django.contrib.auth.models import User

from nose.tools import eq_

import amo.tests
from amo.urlresolvers import reverse
from mkt.api.models import Access


class TestAPI(amo.tests.TestCase):
    fixtures = ['base/users.json']

    def setUp(self):
        self.user = User.objects.get(username='regular@mozilla.com')
        self.create_switch(name='create-api-tokens')
        self.url = reverse('mkt.developers.apps.api')
        self.client.login(username='regular@mozilla.com', password='password')

    def test_logged_out(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_create(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 302)
        eq_(Access.objects.filter(user=self.user).count(), 1)

    def test_delete(self):
        Access.objects.create(user=self.user, key='foo', secret='bar')
        res = self.client.post(self.url, {'delete': 'yep'})
        eq_(res.status_code, 302)
        eq_(Access.objects.filter(user=self.user).count(), 0)

    def test_regenerate(self):
        Access.objects.create(user=self.user, key='foo', secret='bar')
        res = self.client.post(self.url)
        eq_(res.status_code, 302)
        assert Access.objects.get(user=self.user).secret != 'bar'

    def test_admin(self):
        admin = User.objects.get(username='editor@mozilla.com')
        self.client.login(username='editor@mozilla.com', password='password')
        res = self.client.post(self.url, {'delete': 'yep'})
        eq_(res.status_code, 200)
        eq_(Access.objects.filter(user=admin).count(), 0)
