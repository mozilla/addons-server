# -*- coding: utf-8 -*-
import json

from django.core.urlresolvers import NoReverseMatch
from django.test.utils import override_settings

from curling.lib import HttpClientError, HttpServerError
import mock
from nose.tools import eq_

import amo
from amo.tests import app_factory
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import Addon, AddonUser
from users.models import UserProfile

import mkt
from mkt.api.base import get_url, list_url
from mkt.api.tests.test_oauth import BaseOAuth, RestOAuth
from mkt.developers.models import PaymentAccount
from mkt.developers.tests.test_views_payments import setup_payment_account
from mkt.site.fixtures import fixture
from mkt.webapps.models import ContentRating


package_data = {
    'companyName': 'company',
    'vendorName': 'vendor',
    'financeEmailAddress': 'a@a.com',
    'adminEmailAddress': 'a@a.com',
    'supportEmailAddress': 'a@a.com',
    'address1': 'address 1',
    'addressCity': 'city',
    'addressState': 'state',
    'addressZipCode': 'zip',
    'addressPhone': '123',
    'countryIso': 'BRA',
    'currencyIso': 'EUR',
    'account_name': 'account'
}

bank_data = {
    'bankAccountPayeeName': 'name',
    'bankAccountNumber': '123',
    'bankAccountCode': '123',
    'bankName': 'asd',
    'bankAddress1': 'address 2',
    'bankAddressZipCode': '123',
    'bankAddressIso': 'BRA',
}

payment_data = package_data.copy()
payment_data.update(bank_data)


class CreateAccountTests(BaseOAuth):

    def setUp(self):
        BaseOAuth.setUp(self, api_name='payments')

    @mock.patch('mkt.developers.models.client')
    def test_add(self, client):
        r = self.client.post(list_url('account'),
                             data=json.dumps(payment_data))
        eq_(r.status_code, 201)
        pa = PaymentAccount.objects.get(name='account')
        eq_(pa.user.pk, self.user.pk)
        d = client.api.bango.package.post.call_args[1]['data']
        for k, v in d.iteritems():
            if k not in ['paypalEmailAddress', 'seller']:
                eq_(payment_data[k], v)

    @mock.patch('mkt.developers.models.client')
    def test_add_fail(self, client):
        err = {'broken': True}
        client.api.bango.package.post.side_effect = HttpClientError(
            content=err)
        r = self.client.post(list_url('account'),
                             data=json.dumps(payment_data))
        eq_(r.status_code, 500)
        eq_(json.loads(r.content), err)

    @mock.patch('mkt.developers.models.client')
    def test_add_fail2(self, client):
        client.api.bango.package.post.side_effect = HttpServerError()
        r = self.client.post(list_url('account'),
                             data=json.dumps(payment_data))
        eq_(r.status_code, 500)


@mock.patch('mkt.developers.models.client')
class AccountTests(BaseOAuth):
    fixtures = BaseOAuth.fixtures + fixture('webapp_337141', 'user_999')

    def setUp(self):
        BaseOAuth.setUp(self, api_name='payments')
        self.app = Addon.objects.get(pk=337141)
        self.app.update(premium_type=amo.ADDON_FREE_INAPP)
        self.other = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.app, user=self.profile)
        self.account = setup_payment_account(self.app, self.profile,
                                             uid='uid2').payment_account
        self.account.name = 'account'
        self.account.save()

    def test_get_list(self, client):
        client.api.bango.package().get.return_value = {"full": payment_data}

        app2 = app_factory(premium_type=amo.ADDON_FREE_INAPP)
        AddonUser.objects.create(addon=app2, user=self.other)
        setup_payment_account(app2, self.other)

        r = self.client.get(list_url('account'))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        pkg = package_data.copy()
        pkg['resource_uri'] = '/api/v1/payments/account/%s/' % self.account.pk
        eq_(data['objects'], [pkg])

    def test_get(self, client):
        client.api.bango.package().get.return_value = {"full": payment_data}

        r = self.client.get(get_url('account', self.account.pk))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        pkg = package_data.copy()
        pkg['resource_uri'] = '/api/v1/payments/account/%s/' % self.account.pk
        eq_(data, pkg)

    def test_only_get_by_owner(self, client):
        r = self.anon.get(get_url('account', self.account.pk))
        eq_(r.status_code, 401)

    def test_put(self, client):
        addr = 'b@b.com'
        newpkg = package_data.copy()
        newpkg['adminEmailAddress'] = addr
        r = self.client.put(get_url('account', self.account.pk),
                            data=json.dumps(newpkg))
        eq_(r.status_code, 204)
        d = client.api.by_url().patch.call_args[1]['data']
        eq_(d['adminEmailAddress'], addr)

    def test_only_put_by_owner(self, client):
        app2 = app_factory(premium_type=amo.ADDON_FREE_INAPP)
        AddonUser.objects.create(addon=app2, user=self.other)
        acct = setup_payment_account(app2, self.other).payment_account
        r = self.client.put(get_url('account', acct.pk),
                            data=json.dumps(package_data))
        eq_(r.status_code, 404)

    def test_delete(self, client):
        rdel = self.client.delete(get_url('account', self.account.pk))
        eq_(rdel.status_code, 204)

        client.api.bango.package().get.return_value = {"full": payment_data}
        rget = self.client.get(list_url('account'))
        eq_(json.loads(rget.content)['objects'], [])

        account = PaymentAccount.objects.get()
        eq_(account.inactive, True)

    def test_delete_others(self, client):
        rdel = self.client.delete(get_url('account', self.account.pk))
        eq_(rdel.status_code, 204)

        eq_(self.app.reload().status, amo.STATUS_NULL)

    def test_delete_shared(self, client):
        self.account.update(shared=True)
        rdel = self.client.delete(get_url('account', self.account.pk))
        eq_(rdel.status_code, 409)


class TestContentRating(amo.tests.TestCase):

    def setUp(self):
        self.app = app_factory()

    def test_get_content_ratings(self):
        for body in (mkt.ratingsbodies.CLASSIND, mkt.ratingsbodies.ESRB):
            ContentRating.objects.create(addon=self.app, ratings_body=body.id,
                                         rating=0)
        res = self.client.get(reverse('content-ratings-list',
                                      args=[self.app.app_slug]))
        eq_(res.status_code, 200)

        res = json.loads(res.content)
        eq_(len(res['objects']), 2)
        rating = res['objects'][0]
        eq_(rating['body_slug'], 'classind')
        eq_(rating['body_name'], 'CLASSIND')
        eq_(rating['name'], '0+')
        eq_(rating['slug'], '0')
        assert 'description' in rating

    def test_get_content_ratings_since(self):
        cr = ContentRating.objects.create(addon=self.app, ratings_body=0,
                                          rating=0)
        cr.update(modified=self.days_ago(100))

        res = self.client.get(urlparams(
            reverse('content-ratings-list', args=[self.app.app_slug]),
            since=self.days_ago(5)))
        eq_(res.status_code, 404)

        cr.update(modified=self.days_ago(1))
        res = self.client.get(urlparams(
            reverse('content-ratings-list', args=[self.app.id]),
            since=self.days_ago(5)))
        eq_(res.status_code, 200)
        eq_(len(json.loads(res.content)['objects']), 1)

    def test_view_whitelist(self):
        """Only -list, no create/update/delete."""
        with self.assertRaises(NoReverseMatch):
            reverse('content-ratings-create', args=[self.app.id])
        with self.assertRaises(NoReverseMatch):
            reverse('content-ratings-update', args=[self.app.id])
        with self.assertRaises(NoReverseMatch):
            reverse('content-ratings-delete', args=[self.app.id])
        reverse('content-ratings-list', args=[self.app.app_slug])


@override_settings(SECRET_KEY='test')
class TestContentRatingPingback(RestOAuth):

    def setUp(self):
        super(TestContentRatingPingback, self).setUp()
        self.app = app_factory()
        self.url = reverse('content-ratings-pingback', args=[self.app.pk])
        self.data = {
            'ROW': {
                'FIELD': [
                    {
                        'TYPE': 'int',
                        'NAME': 'rowId',
                        'VALUE': '1'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'token',
                        'VALUE': self.app.iarc_token()
                    },
                    {
                        'TYPE': 'int',
                        'NAME': 'submission_id',
                        'VALUE': '321'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'security_code',
                        'VALUE': 'AB12CD3'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'title',
                        'VALUE': 'Twitter'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'company',
                        'VALUE': 'Mozilla'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'platform',
                        'VALUE': 'Firefox'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'rating_PEGI',
                        'VALUE': '18+'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'descriptors_PEGI',
                        'VALUE': 'Language,Gambling'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'rating_USK',
                        'VALUE': '6+'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'descriptors_USK',
                        'VALUE': u'Explizite Sprache,\xC4ngstigende Inhalte'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'rating_ESRB',
                        'VALUE': 'Teen'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'descriptors_ESRB',
                        'VALUE': 'Language,Simulated Gambling'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'rating_CLASSIND',
                        'VALUE': '12+'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'descriptors_CLASSIND',
                        'VALUE': u'Linguagem Impr\xF3pria,Conte\xFAdo Impactante'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'rating_Generic',
                        'VALUE': '12+'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'descriptors_Generic',
                        'VALUE': 'Language,Real Gambling'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'storefront',
                        'VALUE': 'Firefox Marketplace'
                    },
                    {
                        'TYPE': 'string',
                        'NAME': 'interactive_elements',
                        'VALUE': 'Shares Info,Shares Location'
                    }
                ]
            }
        }

    def test_slug_url(self):
        url = reverse('content-ratings-pingback', args=[self.app.app_slug])
        res = self.anon.post(url, data=json.dumps(self.data))
        eq_(res.status_code, 200)

    def test_post_content_ratings_pingback(self):
        res = self.anon.post(self.url, data=json.dumps(self.data))
        eq_(res.status_code, 200)

        # Verify things were saved to the database.
        app = self.app.reload()

        # IARC info.
        eq_(app.iarc_info.submission_id, 321)
        eq_(app.iarc_info.security_code, 'AB12CD3')

        # Ratings.
        eq_(app.content_ratings.count(), 5)
        for rb, rating in [
            (mkt.ratingsbodies.CLASSIND, mkt.ratingsbodies.CLASSIND_12),
            (mkt.ratingsbodies.ESRB, mkt.ratingsbodies.ESRB_T),
            (mkt.ratingsbodies.GENERIC, mkt.ratingsbodies.GENERIC_12),
            (mkt.ratingsbodies.PEGI, mkt.ratingsbodies.PEGI_18),
            (mkt.ratingsbodies.USK, mkt.ratingsbodies.USK_6)]:
            eq_(app.content_ratings.get(ratings_body=rb.id).rating, rating.id,
                'Unexpected rating for rating body %s.' % rb)

        # Descriptors.
        self.assertSetEqual(
            app.rating_descriptors.to_keys(),
            ['has_classind_lang', 'has_classind_shocking',
             'has_pegi_lang', 'has_pegi_gambling',
             'has_generic_lang', 'has_generic_real_gambling',
             'has_esrb_lang', 'has_esrb_sim_gambling',
             'has_usk_lang', 'has_usk_scary'])

        # Interactives.
        self.assertSetEqual(
            app.rating_interactives.to_keys(),
            ['has_shares_info', 'has_shares_location'])

    @override_settings(SECRET_KEY='foo')
    def test_token_mismatch(self):
        res = self.anon.post(self.url, data=json.dumps(self.data))
        eq_(res.status_code, 400)
        eq_(json.loads(res.content)['detail'], 'Token mismatch')
