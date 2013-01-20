from django.conf import settings

import mock
from nose.tools import eq_
from test_utils import RequestFactory

import amo
import amo.tests

from addons.models import Addon, AddonDeviceType
from editors.models import RereviewQueue
from market.models import AddonPremium, Price
from users.models import UserProfile

from mkt.developers import forms_payments, models
from mkt.site.fixtures import fixture


class TestPremiumForm(amo.tests.TestCase):
    # None of the tests in this TC should initiate Solitude calls.
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.request = RequestFactory()
        self.request.POST = {'toggle-paid': ''}

        self.addon = Addon.objects.get(pk=337141)
        AddonDeviceType.objects.create(
            addon=self.addon, device_type=amo.DEVICE_GAIA.id)
        self.platforms = {'free_platforms': ['free-firefoxos'],
                          'paid_platforms': ['paid-firefoxos']}

        self.price = Price.objects.create(price='0.99')
        self.user = UserProfile.objects.get(email='steamcube@mozilla.com')

        self.kwargs = {
            'request': self.request,
            'addon': self.addon,
            'user': self.user,
        }

    def test_free_to_premium(self):
        self.request.POST = {'toggle-paid': 'paid'}
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.premium_type, amo.ADDON_PREMIUM)
        eq_(self.addon.status, amo.STATUS_NULL)

    def test_free_to_premium_pending(self):
        # Pending apps shouldn't get re-reviewed.
        self.addon.update(status=amo.STATUS_PENDING)

        self.request.POST = {'toggle-paid': 'paid'}
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(RereviewQueue.objects.count(), 0)

    def test_premium_to_free(self):
        # Premium to Free is ok for public apps.
        self.make_premium(self.addon)

        self.request.POST = {'toggle-paid': 'free'}
        self.platforms.update(price=self.price.pk)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(RereviewQueue.objects.count(), 0)
        eq_(self.addon.premium_type, amo.ADDON_FREE)
        eq_(self.addon.status, amo.STATUS_PUBLIC)

    def test_add_device(self):
        self.addon.update(status=amo.STATUS_PENDING)
        self.platforms['free_platforms'].append('free-desktop')
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        assert amo.DEVICE_DESKTOP in self.addon.device_types
        eq_(RereviewQueue.objects.count(), 0)
        eq_(self.addon.status, amo.STATUS_PENDING)

    def test_add_device_rereview(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.platforms['free_platforms'].append('free-desktop')
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        assert amo.DEVICE_DESKTOP in self.addon.device_types
        eq_(RereviewQueue.objects.count(), 1)
        eq_(self.addon.status, amo.STATUS_PUBLIC)

    def test_update(self):
        self.make_premium(self.addon)
        price = Price.objects.create(price='9.99')
        self.platforms.update(price=price.pk)
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.premium.price.pk, price.pk)

    def test_update_wo_initial_price(self):
        """Test that if the app doesn't have an initial price (i.e.: it was
        marked as paid during submission) that this is handled gracefully.

        """

        # Don't give the app an initial price.
        AddonPremium.objects.create(addon=self.addon)
        self.addon.premium_type = amo.ADDON_PREMIUM

        price = Price.objects.create(price='9.99')
        self.platforms.update(price=price.pk)
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.premium.price.pk, price.pk)

    def test_update_new_with_acct(self):
        # This was the situation for a new app that was getting linked to an
        # existing bank account.
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        self.platforms.update(price=self.price.pk)
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        addon = Addon.objects.get(pk=self.addon.pk)
        assert addon.premium

    def test_cannot_change_devices_on_toggle(self):
        self.request.POST = {'toggle-paid': 'paid'}
        self.platforms = {'paid_platforms': ['paid-firefoxos']}
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.premium_type, amo.ADDON_PREMIUM)
        eq_(self.addon.status, amo.STATUS_NULL)

        self.assertSetEqual(self.addon.device_types, form.get_devices())

    def test_cannot_change_devices_for_packaged_app(self):
        old_devices = [amo.DEVICE_GAIA]

        self.platforms = {'free_platforms': ['free-desktop']}
        self.addon.update(is_packaged=True)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()

        self.assertSetEqual(self.addon.device_types, old_devices)
        self.assertSetEqual(form.get_devices(), old_devices)

    def test_can_change_devices_for_hosted_app(self):
        # Specify the free and paid. It shouldn't fail because you can't change
        # payment types without explicitly specifying that.
        self.platforms = {'free_platforms': ['free-desktop'],
                          'paid_platforms': ['paid-firefoxos']}  # Ignored.
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()

        self.assertSetEqual(self.addon.device_types, [amo.DEVICE_DESKTOP])


class TestPaidRereview(amo.tests.TestCase):
    fixtures = fixture('webapp_337141') + ['market/prices']

    def setUp(self):
        self.addon = Addon.objects.get(pk=337141)
        self.addon.update(status=amo.STATUS_NULL,
                          highest_status=amo.STATUS_PUBLIC)
        self.price = Price.objects.filter()[0]
        AddonPremium.objects.create(addon=self.addon, price=self.price)
        self.user = UserProfile.objects.get(email='steamcube@mozilla.com')
        amo.set_user(self.user)
        seller = models.SolitudeSeller.objects.create(
            resource_uri='/path/to/sel', user=self.user)

        self.account = models.PaymentAccount.objects.create(
            user=self.user, uri='asdf', name='test', inactive=False,
            solitude_seller=seller, bango_package_id=123)

        self.kwargs = {
            'addon': self.addon,
            'user': self.user,
        }

    @mock.patch('mkt.developers.models.client')
    def test_rereview(self, client):
        client.get_product.return_value = {'meta': {'total_count': 0}}
        client.post_product.return_value = {'resource_uri': 'gpuri'}
        client.get_product_bango.return_value = {'meta': {'total_count': 0}}
        client.post_product_bango.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 123}

        form = forms_payments.BangoAccountListForm(
            data={'accounts': self.account.pk}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        eq_(RereviewQueue.objects.count(), 1)

        form = forms_payments.BangoAccountListForm(None, **self.kwargs)
        assert form.fields['accounts'].empty_label == None

    @mock.patch('mkt.developers.models.client')
    def test_norereview(self, client):
        client.get_product.return_value = {'meta': {'total_count': 0}}
        client.post_product.return_value = {'resource_uri': 'gpuri'}
        client.get_product_bango.return_value = {'meta': {'total_count': 0}}
        client.post_product_bango.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 123}

        self.addon.update(highest_status=amo.STATUS_PENDING)
        form = forms_payments.BangoAccountListForm(
            data={'accounts': self.account.pk}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.status, amo.STATUS_PENDING)
        eq_(RereviewQueue.objects.count(), 0)


class TestRestoreApp(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.addon = Addon.objects.get(pk=337141)
        self.addon.status = amo.STATUS_NULL

    def test_to_public(self):
        self.addon.highest_status = amo.STATUS_PUBLIC
        forms_payments._restore_app(self.addon)
        eq_(self.addon.status, amo.STATUS_PUBLIC)

    def test_to_null(self):
        self.addon.highest_status = amo.STATUS_NULL
        forms_payments._restore_app(self.addon)
        # Apps without a highest status default to PENDING.
        eq_(self.addon.status, amo.STATUS_PENDING)


class TestBangoAccountForm(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        form = forms_payments.BangoPaymentAccountForm()
        self.data = {}
        for field in form.fields:
            if 'currency' in field:
                self.data[field] = 'USD'
            elif 'Iso' in field:
                self.data[field] = 'USA'
            else:
                self.data[field] = 'foo@bu.gs'  # Good enough.

    def test_bank_required(self):
        """When there is no account, require bank details."""

        form = forms_payments.BangoPaymentAccountForm(self.data)
        assert form.is_valid(), form.errors

        del self.data['bankName']
        form = forms_payments.BangoPaymentAccountForm(self.data)
        assert not form.is_valid(), form.errors

    def test_bank_not_required(self):
        """When an account is specified, don't require bank details."""

        account = mock.Mock()

        form = forms_payments.BangoPaymentAccountForm(
            self.data, account=account)
        assert form.is_valid(), form.errors

        del self.data['bankName']
        form = forms_payments.BangoPaymentAccountForm(
            self.data, account=account)
        assert form.is_valid(), form.errors  # Still valid, even now.

    def test_on_save(self):
        """Save should just trigger the account's update function."""

        account = mock.Mock()

        form = forms_payments.BangoPaymentAccountForm(
            self.data, account=account)
        assert form.is_valid(), form.errors

        form.cleaned_data = {'mock': 'talk'}
        form.save()

        account.update_account_details.assert_called_with(mock='talk')
