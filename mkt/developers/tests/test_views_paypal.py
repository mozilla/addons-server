from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import Price, AddonPaymentData
from users.models import UserProfile


# Testing the payments page.
class TestPayments(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube',
                'prices']

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
                 'price': self.price.pk,
                 'support_email': 'foo@bar.com'})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM)

    def test_premium_in_app_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url,
                {'premium_type': amo.ADDON_PREMIUM_INAPP,
                 'price': self.price.pk,
                 'support_email': 'foo@bar.com'})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM_INAPP)

    def test_free_in_app_fails(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url,
                {'premium_type': amo.ADDON_PREMIUM_INAPP,
                 'price': self.price.pk})
        eq_(res.status_code, 200)
        eq_(self.get_webapp().premium_type, amo.ADDON_FREE)

    def test_free_in_app_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url,
                {'premium_type': amo.ADDON_PREMIUM_INAPP,
                 'price': self.price.pk,
                 'support_email': 'foo@bar.com'})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM_INAPP)

    def test_later_then_free(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           status=amo.STATUS_NULL)
        res = self.client.post(self.url, {'premium_type': amo.ADDON_FREE})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.STATUS_PENDING)


# Testing the paypal page.
class TestPaypal(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube',
                'prices']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('paypal_setup')
        user = UserProfile.objects.get(email='admin@mozilla.com')
        user.update(read_dev_agreement=False)

        self.client.login(username='admin@mozilla.com', password='password')
        self.price = Price.objects.all()[0]

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
