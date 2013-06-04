import json

from django.core.urlresolvers import reverse
from nose.tools import eq_

import amo
from addons.models import AddonUpsell, AddonUser
from amo.tests import app_factory, TestCase

from mkt.api.base import get_url
from mkt.api.tests.test_oauth import RestOAuth, get_absolute_url
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class UpsellCase(TestCase):

    def url(self, app):
        return get_absolute_url(get_url('app', pk=app.pk), absolute=False)

    def setUp(self):
        self.free = Webapp.objects.get(pk=337141)
        self.free_url = self.url(self.free)
        self.premium = app_factory(premium_type=amo.ADDON_PREMIUM)
        self.premium_url = self.url(self.premium)
        self.upsell_list = reverse('app-upsell-list')

    def create_upsell(self):
        self.upsell = AddonUpsell.objects.create(free=self.free,
                                                 premium=self.premium)
        self.upsell_url = reverse('app-upsell-detail',
                                  kwargs={'pk': self.upsell.pk})

    def create_allowed(self):
        AddonUser.objects.create(addon=self.free, user=self.profile)
        AddonUser.objects.create(addon=self.premium, user=self.profile)


class TestUpsell(RestOAuth, UpsellCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestUpsell, self).setUp()
        UpsellCase.setUp(self)

    def test_create(self):
        eq_(self.client.post(self.upsell_list, data={}).status_code, 400)

    def test_missing(self):
        res = self.client.post(self.upsell_list,
                               data=json.dumps({'free': self.free_url}))
        eq_(res.status_code, 400)
        eq_(res.json['premium'], [u'This field is required.'])

    def test_not_allowed(self):
        res = self.client.post(self.upsell_list, data=json.dumps(
            {'free': self.free_url, 'premium': self.premium_url}))
        eq_(res.status_code, 403)

    def test_allowed(self):
        self.create_allowed()
        res = self.client.post(self.upsell_list, data=json.dumps(
            {'free': self.free_url, 'premium': self.premium_url}))
        eq_(res.status_code, 201)

    def test_delete_not_allowed(self):
        self.create_upsell()
        eq_(self.client.delete(self.upsell_url).status_code, 403)

    def test_delete_allowed(self):
        self.create_upsell()
        self.create_allowed()
        eq_(self.client.delete(self.upsell_url).status_code, 204)

    def test_wrong_way_around(self):
        res = self.client.post(self.upsell_list, data=json.dumps(
            {'free': self.premium_url, 'premium': self.free_url}))
        eq_(res.status_code, 400)

    def test_patch_new_not_allowed(self):
        # Trying to patch to a new object you do not have access to.
        self.create_upsell()
        self.create_allowed()
        another = app_factory(premium_type=amo.ADDON_PREMIUM)
        res = self.client.patch(self.upsell_url, data=json.dumps(
            {'free': self.free_url, 'premium': self.url(another)}))
        eq_(res.status_code, 403)

    def test_patch_old_not_allowed(self):
        # Trying to patch an old object you do not have access to.
        self.create_upsell()
        AddonUser.objects.create(addon=self.free, user=self.profile)
        # We did not give you access to patch away from self.premium.
        another = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUser.objects.create(addon=another, user=self.profile)
        res = self.client.patch(self.upsell_url, data=json.dumps(
            {'free': self.free_url, 'premium': self.url(another)}))
        eq_(res.status_code, 403)

    def test_patch(self):
        self.create_upsell()
        self.create_allowed()
        another = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUser.objects.create(addon=another, user=self.profile)
        res = self.client.patch(self.upsell_url, data=json.dumps(
            {'free': self.free_url, 'premium': self.url(another)}))
        eq_(res.status_code, 200)


class TestPayment(RestOAuth, UpsellCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestPayment, self).setUp()
        UpsellCase.setUp(self)
        self.payment_url = reverse('app-payments-detail',
                                   kwargs={'pk': 337141})

    def test_get_not_allowed(self):
        res = self.client.get(self.payment_url)
        eq_(res.status_code, 403)

    def test_get_allowed(self):
        AddonUser.objects.create(addon_id=337141, user=self.profile)
        res = self.client.get(self.payment_url)
        eq_(res.json['upsell'], None)
        eq_(res.status_code, 200)

    def test_upsell(self):
        AddonUser.objects.create(addon_id=337141, user=self.profile)
        upsell = AddonUpsell.objects.create(free_id=337141,
                                            premium=self.premium)
        res = self.client.get(self.payment_url)
        eq_(res.json['upsell'],
            reverse('app-upsell-detail', kwargs={'pk': upsell.pk}))
        eq_(res.status_code, 200)
