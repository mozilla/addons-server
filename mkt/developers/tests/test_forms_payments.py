import mock
from nose.tools import eq_, ok_
from pyquery import PyQuery as pq
from test_utils import RequestFactory

import amo
import amo.tests

from addons.models import Addon, AddonDeviceType, AddonUser
from constants.payments import (PAYMENT_METHOD_OPERATOR,
                                PAYMENT_METHOD_CARD,
                                PAYMENT_METHOD_ALL)
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

    def test_free_with_in_app_requires_in_app(self):
        self.platforms.update(price='free', allow_inapp='False')
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert not form.is_valid()

    def test_free_with_in_app(self):
        self.make_premium(self.addon)
        self.platforms.update(price='free', allow_inapp='True')
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert form.is_valid()
        form.save()
        eq_(self.addon.premium_type, amo.ADDON_FREE_INAPP)

    def test_tier_zero_inapp_is_optional(self):
        self.platforms.update(price='free', allow_inapp='False')
        price = Price.objects.create(price='9.99')
        self.platforms.update(price=price.pk, allow_inapp='True')
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert form.is_valid()
        self.platforms.update(price=price.pk, allow_inapp='False')
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        assert form.is_valid()

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

    def test_is_paid_premium(self):
        self.make_premium(self.addon)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        eq_(form.is_paid(), True)

    def test_free_inapp_price_required(self):
        self.addon.update(premium_type=amo.ADDON_FREE_INAPP)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert not form.is_valid()

    def test_is_paid_premium_inapp(self):
        self.addon.update(premium_type=amo.ADDON_PREMIUM_INAPP)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        eq_(form.is_paid(), True)

    def test_is_paid_free_inapp(self):
        self.addon.update(premium_type=amo.ADDON_FREE_INAPP)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        eq_(form.is_paid(), True)

    def test_not_is_paid_free(self):
        self.addon.update(premium_type=amo.ADDON_FREE)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        eq_(form.is_paid(), False)

    def test_add_device(self):
        self.addon.update(status=amo.STATUS_PENDING)
        self.platforms['free_platforms'].append('free-desktop')
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        assert amo.DEVICE_DESKTOP in self.addon.device_types
        eq_(RereviewQueue.objects.count(), 0)
        eq_(self.addon.status, amo.STATUS_PENDING)

    def test_add_device_public_rereview(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.platforms['free_platforms'].append('free-desktop')
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        assert amo.DEVICE_DESKTOP in self.addon.device_types
        eq_(RereviewQueue.objects.count(), 1)
        eq_(self.addon.status, amo.STATUS_PUBLIC)

    def test_add_device_publicwaiting_rereview(self):
        self.addon.update(status=amo.STATUS_PUBLIC_WAITING)
        self.platforms['free_platforms'].append('free-desktop')
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        assert amo.DEVICE_DESKTOP in self.addon.device_types
        eq_(RereviewQueue.objects.count(), 1)
        eq_(self.addon.status, amo.STATUS_PUBLIC_WAITING)

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

    def test_update_with_bogus_price(self):
        AddonPremium.objects.create(addon=self.addon)
        self.addon.premium_type = amo.ADDON_PREMIUM
        self.platforms.update(price='bogus')
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        eq_(form.is_valid(), False)
        eq_(len(form.errors), 1)
        ok_('price' in form.errors)

    def test_premium_with_empty_price(self):
        AddonPremium.objects.create(addon=self.addon)
        self.addon.premium_type = amo.ADDON_PREMIUM
        self.platforms.update(price='')
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        eq_(form.is_valid(), False)
        eq_(len(form.errors), 1)
        ok_('price' in form.errors)

    def test_premium_with_price_does_not_exist(self):
        AddonPremium.objects.create(addon=self.addon)
        self.addon.premium_type = amo.ADDON_PREMIUM
        self.platforms.update(price=9999)
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        form.fields['price'].choices = ((9999, 'foo'),)
        eq_(form.is_valid(), False)
        eq_(len(form.errors), 1)
        ok_('price' in form.errors)

    def test_optgroups_in_price_choices(self):
        Price.objects.create(price='0.00', method=PAYMENT_METHOD_ALL)
        Price.objects.create(price='0.10', method=PAYMENT_METHOD_OPERATOR)
        Price.objects.create(price='1.00', method=PAYMENT_METHOD_CARD)
        Price.objects.create(price='1.10', method=PAYMENT_METHOD_CARD)
        Price.objects.create(price='1.00', method=PAYMENT_METHOD_ALL)
        Price.objects.create(price='2.00', method=PAYMENT_METHOD_ALL)
        form = forms_payments.PremiumForm(self.platforms, **self.kwargs)
        #   1 x Free with inapp
        # + 1 x price tier 0
        # + 3 x values grouped by billing
        # = 5
        eq_(len(form.fields['price'].choices), 5)
        html = form.as_p()
        eq_(len(pq(html)('#id_price optgroup')), 3, 'Should be 3 optgroups')

    def test_cannot_change_devices_on_toggle(self):
        self.request.POST = {'toggle-paid': 'paid'}
        self.platforms = {'paid_platforms': ['paid-firefoxos']}
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.premium_type, amo.ADDON_PREMIUM)
        eq_(self.addon.status, amo.STATUS_NULL)

        self.assertSetEqual(self.addon.device_types, form.get_devices())

    def test_cannot_set_desktop_for_packaged_app(self):
        self.platforms = {'free_platforms': ['free-desktop']}
        self.addon.update(is_packaged=True)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert not form.is_valid()

    def test_can_set_desktop_for_packaged_app(self):
        self.create_flag('desktop-packaged')
        self.platforms = {'free_platforms': ['free-desktop']}
        self.addon.update(is_packaged=True)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors

    def test_can_change_devices_for_hosted_app(self):
        # Specify the free and paid. It shouldn't fail because you can't change
        # payment types without explicitly specifying that.
        self.platforms = {'free_platforms': ['free-desktop'],
                          'paid_platforms': ['paid-firefoxos']}  # Ignored.
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()

        self.assertSetEqual(self.addon.device_types, [amo.DEVICE_DESKTOP])

    def test_cannot_change_android_devices_for_packaged_app(self):
        self.platforms = {'free_platforms': ['free-android-mobile'],
                          'paid_platforms': ['paid-firefoxos']}  # Ignored.
        self.addon.update(is_packaged=True)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert not form.is_valid()

        self.assertSetEqual(self.addon.device_types, [amo.DEVICE_GAIA])

    def test_can_change_devices_for_packaged_app_behind_flag(self):
        self.create_flag('android-packaged')
        self.platforms = {'free_platforms': ['free-android-mobile'],
                          'paid_platforms': ['paid-firefoxos']}  # Ignored.
        self.addon.update(is_packaged=True)
        form = forms_payments.PremiumForm(data=self.platforms, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()

        self.assertSetEqual(self.addon.device_types, [amo.DEVICE_MOBILE])

    def test_can_change_devices_for_android_app_behind_flag(self):
        self.create_flag('android-payments')
        data = {'paid_platforms': ['paid-firefoxos', 'paid-android-mobile'],
                'price': 'free', 'allow_inapp': 'True'}
        self.make_premium(self.addon)
        form = forms_payments.PremiumForm(data=data, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        self.assertSetEqual(self.addon.device_types, [amo.DEVICE_MOBILE,
                                                      amo.DEVICE_GAIA])

    def test_initial(self):
        form = forms_payments.PremiumForm(**self.kwargs)
        eq_(form._initial_price_id(), Price.objects.get(price='0.99').pk)

    def test_initial_not_there(self):
        Price.objects.get(price='0.99').update(active=False)
        form = forms_payments.PremiumForm(**self.kwargs)
        eq_(form._initial_price_id(), None)


class TestAccountListForm(amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999', 'group_admin',
                       'user_admin', 'user_admin_group', 'prices')

    def setUp(self):
        self.addon = Addon.objects.get(pk=337141)
        self.addon.update(status=amo.STATUS_NULL,
                          highest_status=amo.STATUS_PUBLIC)
        self.price = Price.objects.filter()[0]
        AddonPremium.objects.create(addon=self.addon, price=self.price)

        self.user = UserProfile.objects.get(pk=31337)
        amo.set_user(self.user)

        self.other = UserProfile.objects.get(pk=999)
        self.admin = UserProfile.objects.get(email='admin@mozilla.com')

        self.kwargs = {
            'addon': self.addon,
        }

    def create_user_account(self, user, **kwargs):
        """Create a user account"""
        seller = models.SolitudeSeller.objects.create(
            resource_uri='/path/to/sel', user=user, uuid='uuid-%s' % user.pk)

        data = dict(user=user, uri='asdf-%s' % user.pk, name='test',
                    inactive=False, solitude_seller=seller,
                    seller_uri='suri-%s' % user.pk, account_id=123,
                    agreed_tos=True, shared=False)
        data.update(**kwargs)
        return models.PaymentAccount.objects.create(**data)

    def make_owner(self, user):
        AddonUser.objects.create(addon=self.addon,
                                 user=user, role=amo.AUTHOR_ROLE_OWNER)

    def is_owner(self, user):
        return (self.addon.authors.filter(user=user,
                addonuser__role=amo.AUTHOR_ROLE_OWNER).exists())

    @mock.patch('mkt.developers.models.client')
    def associate_owner_account(self, client):
        self.setup_mock(client)

        owner_account = self.create_user_account(self.user)
        form = forms_payments.AccountListForm(
            data={'accounts': owner_account.pk}, user=self.user, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        return owner_account

    def setup_mock(self, client):
        client.get_product.return_value = {'meta': {'total_count': 0}}
        client.post_product.return_value = {'resource_uri': 'gpuri'}
        client.get_product_bango.return_value = {'meta': {'total_count': 0}}
        client.post_product_bango.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 123}

    @mock.patch('mkt.developers.models.client')
    def test_with_owner_account(self, client):
        self.setup_mock(client)

        user = self.user
        account = self.create_user_account(user)
        assert self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)
        eq_(form.current_payment_account, None)
        assert form.is_valid(), form.errors
        form.save()
        form = forms_payments.AccountListForm(None, user=user,
                                                  **self.kwargs)
        eq_(form.fields['accounts'].widget.attrs.get('disabled'), None)
        eq_(form.fields['accounts'].empty_label, None)
        eq_(form.initial['accounts'], account)

    @mock.patch('mkt.developers.models.client')
    def test_with_shared_account(self, client):
        self.setup_mock(client)

        account = self.create_user_account(self.user)
        shared = self.create_user_account(self.other, shared=True)
        form = forms_payments.AccountListForm(user=self.user,
                                                   **self.kwargs)
        self.assertSetEqual(form.fields['accounts'].queryset,
                            (account, shared))

    @mock.patch('mkt.developers.models.client')
    def test_set_shared_account(self, client):
        self.setup_mock(client)

        shared = self.create_user_account(self.other, shared=True)
        form = forms_payments.AccountListForm(
            data={'accounts': shared.pk}, user=self.user, **self.kwargs)
        assert form.is_valid()
        form.save()
        eq_(self.addon.app_payment_account.payment_account.pk, shared.pk)

    @mock.patch('mkt.developers.models.client')
    def test_with_non_owner_account(self, client):
        self.setup_mock(client)

        user = self.other
        account = self.create_user_account(user)
        assert not self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)
        eq_(form.current_payment_account, None)
        assert form.fields['accounts'].widget.attrs['disabled'] is not None
        assert not form.is_valid(), form.errors

    @mock.patch('mkt.developers.models.client')
    def test_with_non_owner_admin_account(self, client):
        self.setup_mock(client)

        user = self.admin
        account = self.create_user_account(user)
        assert not self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)
        eq_(form.current_payment_account, None)
        assert form.fields['accounts'].widget.attrs['disabled'] is not None
        assert not form.is_valid(), form.errors

    @mock.patch('mkt.developers.models.client')
    def test_admin_account_no_data(self, client):
        self.setup_mock(client)

        self.associate_owner_account()
        user = self.admin
        assert not self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={}, user=user, **self.kwargs)
        assert form.fields['accounts'].widget.attrs['disabled'] is not None
        assert form.is_valid(), form.errors

    @mock.patch('mkt.developers.models.client')
    def test_admin_account_empty_string(self, client):
        self.setup_mock(client)

        self.associate_owner_account()
        user = self.admin
        assert not self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': ''}, user=user, **self.kwargs)
        assert form.fields['accounts'].widget.attrs['disabled'] is not None
        assert not form.is_valid(), form.errors

    @mock.patch('mkt.developers.models.client')
    def test_with_other_owner_account(self, client):
        self.setup_mock(client)

        user = self.other
        account = self.create_user_account(user)
        self.make_owner(user)
        assert self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)
        assert form.is_valid(), form.errors
        eq_(form.current_payment_account, None)
        eq_(form.fields['accounts'].widget.attrs.get('disabled'), None)
        form.save()
        form = forms_payments.AccountListForm(None, user=user,
                                                   **self.kwargs)
        eq_(form.fields['accounts'].empty_label, None)
        eq_(form.initial['accounts'], account)

    @mock.patch('mkt.developers.models.client')
    def test_with_non_owner_account_existing_account(self, client):
        self.setup_mock(client)

        owner_account = self.associate_owner_account()
        user = self.other
        account = self.create_user_account(user)
        assert not self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)

        assert form.fields['accounts'].widget.attrs['disabled'] is not None
        eq_(form.current_payment_account, owner_account)
        assert not form.is_valid(), form.errors

    @mock.patch('mkt.developers.models.client')
    def test_with_non_owner_admin_account_existing_account(self, client):
        self.setup_mock(client)

        owner_account = self.associate_owner_account()
        user = self.admin
        account = self.create_user_account(user)
        assert not self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)

        assert form.fields['accounts'].widget.attrs['disabled'] is not None
        eq_(form.current_payment_account, owner_account)
        assert not form.is_valid(), form.errors

    @mock.patch('mkt.developers.models.client')
    def test_with_other_owner_account_existing_account(self, client):
        self.setup_mock(client)

        owner_account = self.associate_owner_account()
        user = self.other
        account = self.create_user_account(user)
        self.make_owner(user)
        assert self.is_owner(user)
        form = forms_payments.AccountListForm(
            data={'accounts': account.pk}, user=user, **self.kwargs)
        eq_(form.current_payment_account, owner_account)
        assert form.is_valid(), form.errors
        form.save()
        form = forms_payments.AccountListForm(None, user=user,
                                                   **self.kwargs)
        eq_(form.fields['accounts'].empty_label, None)
        eq_(form.initial['accounts'], account)
        assert form.current_payment_account is None


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
            solitude_seller=seller, account_id=123, agreed_tos=True)

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

        form = forms_payments.AccountListForm(
            data={'accounts': self.account.pk}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        eq_(RereviewQueue.objects.count(), 1)

        form = forms_payments.AccountListForm(None, **self.kwargs)
        eq_(form.fields['accounts'].empty_label, None)

    @mock.patch('mkt.developers.models.client')
    def test_disagreed_tos_rereview(self, client):
        self.account.update(agreed_tos=False)
        client.get_product.return_value = {'meta': {'total_count': 0}}
        client.post_product.return_value = {'resource_uri': 'gpuri'}
        client.get_product_bango.return_value = {'meta': {'total_count': 0}}
        client.post_product_bango.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 123}

        form = forms_payments.AccountListForm(
            data={'accounts': self.account.pk}, **self.kwargs)
        assert not form.is_valid()
        eq_(form.errors['accounts'],
            ['Select a valid choice. That choice is not one of the available '
             'choices.'])

    @mock.patch('mkt.developers.models.client')
    def test_norereview(self, client):
        client.get_product.return_value = {'meta': {'total_count': 0}}
        client.post_product.return_value = {'resource_uri': 'gpuri'}
        client.get_product_bango.return_value = {'meta': {'total_count': 0}}
        client.post_product_bango.return_value = {
            'resource_uri': 'bpruri', 'bango_id': 123}

        self.addon.update(highest_status=amo.STATUS_PENDING)
        form = forms_payments.AccountListForm(
            data={'accounts': self.account.pk}, **self.kwargs)
        assert form.is_valid(), form.errors
        form.save()
        eq_(self.addon.status, amo.STATUS_PENDING)
        eq_(RereviewQueue.objects.count(), 0)


class TestRestoreAppStatus(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.addon = Addon.objects.get(pk=337141)
        self.addon.status = amo.STATUS_NULL

    def test_to_public(self):
        self.addon.highest_status = amo.STATUS_PUBLIC
        forms_payments._restore_app_status(self.addon)
        eq_(self.addon.status, amo.STATUS_PUBLIC)

    def test_to_null(self):
        self.addon.highest_status = amo.STATUS_NULL
        forms_payments._restore_app_status(self.addon)
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
