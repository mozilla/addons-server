# -*- coding: utf-8 -*-
import json

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import AddonCategory, Category
import amo
import amo.tests
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from market.models import AddonPremium, AddonPurchase
from users.models import UserProfile

from mkt.webapps.models import Webapp
from mkt.site.helpers import market_button, market_tile


class TestMarketButton(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        request = mock.Mock()
        request.amo_user = self.user
        request.groups = ()
        request.check_ownership.return_value = False
        request.GET = {'src': 'foo'}
        request.groups = ()
        self.context = {'request': request}

    def test_not_webapp(self):
        self.webapp.update(type=amo.ADDON_EXTENSION)
        # TODO: raise a more sensible error.
        self.assertRaises(UnboundLocalError, market_button,
                          self.context, self.webapp)

    def test_is_webapp(self):
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['manifestUrl'], self.webapp.manifest_url)
        eq_(data['recordUrl'], urlparams(self.webapp.get_detail_url('record'),
                                         src='foo'))
        eq_(data['preapprovalUrl'], reverse('detail.purchase.preapproval',
                                            args=[self.webapp.app_slug]))
        eq_(data['id'], str(self.webapp.pk))
        eq_(data['name'], self.webapp.name)

    def test_is_premium_webapp(self):
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['manifestUrl'], self.webapp.manifest_url)
        eq_(data['price'], 1.0)
        eq_(data['priceLocale'], '$1.00')
        eq_(data['purchase'], self.webapp.get_purchase_url())
        eq_(data['isPurchased'], False)

    def test_is_premium_webapp_foreign(self):
        self.make_premium(self.webapp)
        with self.activate('fr'):
            doc = pq(market_tile(self.context, self.webapp))
            data = json.loads(doc('.mkt-tile').attr('data-product'))
            eq_(data['price'], 1.0)
            eq_(data['priceLocale'], u'1,00 €')

    def test_is_premium_purchased(self):
        AddonPurchase.objects.create(user=self.user, addon=self.webapp)
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['isPurchased'], True)

    def test_xss(self):
        nasty = '<script>'
        escaped = '&lt;script&gt;'
        author = self.webapp.authors.all()[0]
        author.display_name = nasty
        author.save()

        self.webapp.name = nasty
        self.webapp.save()
        Webapp.transformer([self.webapp])  # Transform `listed_authors`, etc.

        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['name'], escaped)
        eq_(data['author'], escaped)

    def test_default_supported_currencies(self):
        self.make_premium(self.webapp)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        assert 'currencies' not in data

    @mock.patch('mkt.site.helpers.waffle.switch_is_active')
    def test_some_supported_currencies(self, switch_is_active):
        switch_is_active.return_value = True
        self.make_premium(self.webapp, currencies=['CAD'])
        ad = AddonPremium.objects.get(addon=self.webapp)
        ad.update(currencies=['USD', 'CAD'])
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(json.loads(data['currencies'])['USD'], '$1.00')
        eq_(json.loads(data['currencies'])['CAD'], 'CA$1.00')

    @mock.patch('mkt.site.helpers.acl.check_reviewer')
    def test_reviewers(self, check_reviewer):
        check_reviewer.return_value = True
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        issue = urlparams(reverse('receipt.issue',
                                  args=[self.webapp.app_slug]), src='foo')
        eq_(data['recordUrl'], issue)

    def test_category(self):
        c = Category.objects.create(name='test-cat', type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.webapp, category=c)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('.mkt-tile').attr('data-product'))
        eq_(data['categories'],
            [str(cat.name) for cat in self.webapp.categories.all()])

    def test_is_packaged(self):
        self.webapp.update(is_packaged=True)
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('a').attr('data-product'))
        eq_(data['is_packaged'], True)
        assert data['package_url'].startswith('/downloads')

    def test_is_not_packaged(self):
        doc = pq(market_tile(self.context, self.webapp))
        data = json.loads(doc('a').attr('data-product'))
        eq_(data['is_packaged'], False)
        eq_(data['package_url'], '')
