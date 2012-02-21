from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from market.models import Price


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


# Testing the paypal page.
class TestPaypal(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube',
                'prices']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('paypal_setup')
        self.client.login(username='admin@mozilla.com', password='password')
        self.price = Price.objects.all()[0]

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_not_premium(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.get(self.url)
        eq_(res.status_code, 302)
