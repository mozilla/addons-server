import json

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from users.models import UserProfile

import mock
from nose.tools import eq_


class TestWebapp(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(type=amo.ADDON_WEBAPP)
        self.user = UserProfile.objects.get(pk=999)


@mock.patch('addons.models.Addon.is_premium', lambda x: True)
class TestAddonPurchase(TestWebapp):

    def setUp(self):
        super(TestAddonPurchase, self).setUp()
        self.url = reverse('api.market.verify', args=[self.addon.slug])

    def test_anonymous(self):
        eq_(self.client.get(self.url).status_code, 302)

    def test_wrong_type(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.update(type=amo.ADDON_EXTENSION)
        res = self.client.get(self.url)
        eq_(res.status_code, 400)

    def test_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'invalid')

    def test_logged_in_ok(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'ok')

    def test_logged_in_other(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'invalid')

    def test_user_not_purchased(self):
        eq_(list(self.user.purchase_ids()), [])

    def test_user_purchased(self):
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        eq_(list(self.user.purchase_ids()), [3615L])


class TestGetManifest(TestWebapp):

    def setUp(self):
        super(TestGetManifest, self).setUp()
        self.addon.update(manifest_url='http://some.manifest.com/web.app')
        self.url = reverse('api.market.urls')
        self.client.login(username='regular@mozilla.com', password='password')

    def test_anonymous(self):
        self.client.logout()
        eq_(self.client.get(self.url).status_code, 302)

    def test_logged_in(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content), [])

    def test_purchased_not_asked(self):
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content), [])

    def test_purchased_asked(self):
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        res = self.client.get(self.url + '?ids=%s' % self.addon.pk)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data[0]['id'], self.addon.pk)
        eq_(data[0]['manifest_url'], self.addon.manifest_url)

    def test_purchase_asked_different(self):
        addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        res = self.client.get(self.url + '?ids=%s&ids=%s' %
                                         (self.addon.pk, addon.pk))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        # Note that addon is not present.
        eq_(len(data), 1)
        eq_(data[0]['id'], self.addon.pk)

    def test_purchase_multiple(self):
        addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
        addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        self.addon.addonpurchase_set.create(user=self.user,
                                            receipt='yak.shave')
        res = self.client.get(self.url + '?ids=%s&ids=%s' %
                                         (self.addon.pk, addon.pk))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        # Note that addon is not present.
        eq_(len(data), 2)
        eq_(set(i['id'] for i in data), set([addon.pk, self.addon.pk]))
