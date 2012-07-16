import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import AddonPaymentData, AddonPremium, Price
from users.models import UserProfile


# Testing the payments page.
class TestPayments(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube',
                'market/prices']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('payments')
        self.client.login(username='admin@mozilla.com', password='password')
        self.price = Price.objects.all()[0]

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_free(self):
        res = self.client.post(self.url, {'premium_type': amo.ADDON_FREE})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_FREE)

    def test_premium_fails(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url, {'premium_type': amo.ADDON_PREMIUM})
        eq_(res.status_code, 200)
        eq_(self.get_webapp().premium_type, amo.ADDON_FREE)

    def test_premium_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url,
                {'premium_type': amo.ADDON_PREMIUM,
                 'price': self.price.pk})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM)

    def test_premium_in_app_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url,
                {'premium_type': amo.ADDON_PREMIUM_INAPP,
                 'price': self.price.pk})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM_INAPP)

    def test_free_in_app_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url,
                {'premium_type': amo.ADDON_PREMIUM_INAPP,
                 'price': self.price.pk})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM_INAPP)

    def test_later_then_free(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           status=amo.STATUS_NULL)
        res = self.client.post(self.url, {'premium_type': amo.ADDON_FREE})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.STATUS_PENDING)

    def test_later_then_free_with_paypal_id(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           status=amo.STATUS_NULL,
                           paypal_id='a@a.com')
        res = self.client.post(self.url, {'premium_type': amo.ADDON_FREE})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.STATUS_PENDING)

    def test_premium_price_initial_already_set(self):
        Price.objects.create(price='0.00')  # Make a free tier for measure.
        self.make_premium(self.webapp)
        r = self.client.get(self.url)
        eq_(pq(r.content)('select[name=price] option[selected]').attr('value'),
            str(self.webapp.premium.price.id))

    def test_premium_price_initial_use_default(self):
        Price.objects.create(price='10.00')  # Make one more tier.
        r = self.client.get(self.url, {'poop': True})
        eq_(pq(r.content)('select[name=price] option[selected]').attr('value'),
            str(Price.objects.get(price='0.99').id))


class TestPaypal(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube',
                'market/prices']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('paypal_setup')
        user = UserProfile.objects.get(email='admin@mozilla.com')
        user.update(read_dev_agreement=False)

        self.client.login(username='admin@mozilla.com', password='password')
        self.price = Price.objects.all()[0]
        AddonPremium.objects.create(addon=self.webapp)

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_not_premium(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.get(self.url)
        eq_(res.status_code, 302)

    def test_partial_submit(self):
        from mkt.submit.models import AppSubmissionChecklist
        AppSubmissionChecklist.objects.create(addon=self.webapp)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.get(self.url, follow=True)
        self.assertRedirects(res, reverse('submit.app.terms'))

    @mock.patch('mkt.developers.views.waffle.switch_is_active')
    def test_currencies_fails(self, switch_is_active):
        switch_is_active.return_value = True
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.url, {'currencies': ['GBP', 'EUR'],
                                          'form': 'currency'})
        eq_(res.status_code, 200)
        self.assertFormError(res, 'currency_form', 'currencies',
                              [u'Select a valid choice. '
                                'GBP is not one of the available choices.'])

    @mock.patch('mkt.developers.views.waffle.switch_is_active')
    def test_currencies_passes(self, switch_is_active):
        switch_is_active.return_value = True
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.url, {'currencies': ['EUR', 'BRL'],
                                          'form': 'currency'})
        eq_(res.status_code, 302)
        eq_(self.webapp.premium.currencies, ['EUR', 'BRL'])

    def test_later(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.url, {'email': 'a@a.com',
                                          'business_account': 'yes',
                                          'form': 'paypal'})
        self.assertRedirects(res,
                             self.webapp.get_dev_url('paypal_setup_bounce'))

    @mock.patch('mkt.developers.views.client')
    @mock.patch('mkt.developers.views.waffle.flag_is_active')
    def test_later_solitude(self, flag_is_active, client):
        flag_is_active.return_value = True
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        self.client.post(self.url, {'email': 'a@a.com', 'form': 'paypal',
                                    'business_account': 'yes'})
        eq_(client.create_seller_paypal.call_args[0][0], self.webapp)
        eq_(client.patch_seller_paypal.call_args[1]['data']['paypal_id'],
            'a@a.com')

    @mock.patch('mkt.developers.views.client')
    def test_bounce_solitude(self, client):
        self.create_flag(name='solitude-payments')
        url = 'http://foo.com'
        client.post_permission_url.return_value = {'token': url}
        self.webapp.update(premium_type=amo.ADDON_PREMIUM, paypal_id='a@.com')
        res = self.client.post(self.webapp.get_dev_url('paypal_setup_bounce'))
        eq_(pq(res.content)('section.primary a.button').attr('href'), url)


class TestPaypalResponse(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('paypal_setup_confirm')
        self.webapp.update(status=amo.STATUS_NULL)
        self.client.login(username='admin@mozilla.com', password='password')

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_paypal_updates(self):
        self.webapp.update(status=amo.STATUS_NULL, paypal_id='bob@dog.com')
        AddonPaymentData.objects.create(addon=self.webapp)
        res = self.client.post(self.url, {'country': 'bob',
                                          'address_one': '123 bob st.'})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.WEBAPPS_UNREVIEWED_STATUS)

    def test_not_paypal_updates(self):
        self.webapp.update(status=amo.STATUS_PUBLIC, paypal_id='bob@dog.com')
        AddonPaymentData.objects.create(addon=self.webapp)
        res = self.client.post(self.url, {'country': 'bob',
                                          'address_one': '123 bob st.'})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.STATUS_PUBLIC)

    # These next two tests test strings, which sucks, but it's pretty much
    # the only change that occurs.
    def test_payment_confirm(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('h1').eq(1).text(), 'Confirm Details')

    def test_payment_details(self):
        res = self.client.get(self.webapp.get_dev_url('paypal_setup_details'))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('h1').eq(1).text(), 'Contact Details')

    def test_payment_changes(self):
        adp = AddonPaymentData.objects.create(addon=self.webapp, country='ca',
                                              address_one='123 bob st.')
        res = self.client.post(self.url, {'country': 'uk',
                                          'address_one': '123 bob st.'})
        eq_(res.status_code, 302)
        eq_(AddonPaymentData.objects.get(pk=adp.pk).country, 'uk')

    def test_required_fields(self):
        res = self.client.post(self.url, {'name': 'muppet'})
        eq_(res.status_code, 200)
        for field in ('country', 'address_one'):
            self.assertFormError(res, 'form', field,
                                 [u'This field is required.'])

    @mock.patch('mkt.developers.views.client')
    def test_payment_reads_solitude(self, client):
        self.create_flag(name='solitude-payments')
        client.get_seller_paypal_if_exists.return_value = {'country': 'fr'}
        res = self.client.get(self.url)
        eq_(res.context['form'].data['country'], 'fr')

    @mock.patch('mkt.developers.views.client')
    def test_payment_reads_solitude_but_empty(self, client):
        AddonPaymentData.objects.create(addon=self.webapp, country='ca',
                                        address_one='123 bob st.')
        self.create_flag(name='solitude-payments')
        client.get_seller_paypal_if_exists.return_value = None
        res = self.client.get(self.url)
        eq_(res.context['form'].data['country'], 'ca')

    @mock.patch('mkt.developers.views.client')
    def test_payment_confirm_solitude(self, client):
        self.create_flag(name='solitude-payments')
        client.create_seller_for_pay.return_value = 1
        res = self.client.post(self.url, {'country': 'uk',
                                          'address_one': '123 bob st.'})
        args = client.patch_seller_paypal.call_args[1]
        eq_(args['data']['address_one'], '123 bob st.')
        eq_(args['pk'], 1)
        eq_(res.status_code, 302)
