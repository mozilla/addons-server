from django import forms
from django.conf import settings

import commonware
import happyforms
import waffle
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.utils import raise_required
import paypal
from addons.models import Addon, AddonUpsell
from editors.models import RereviewQueue
from lib.pay_server import client
from market.models import AddonPremium, Price, PriceCurrency

from mkt.constants import FREE_PLATFORMS, PAID_PLATFORMS
from mkt.inapp_pay.models import InappConfig
from mkt.site.forms import AddonChoiceField

from .models import AddonPaymentAccount, PaymentAccount


log = commonware.log.getLogger('z.devhub')


class PremiumForm(happyforms.Form):
    """
    The premium details for an addon, which is unfortunately
    distributed across a few models.
    """

    allow_inapp = forms.BooleanField(
        label=_lazy(u'Allow In-App Purchases?'), required=False)
    price = forms.ModelChoiceField(queryset=Price.objects.active(),
                                   label=_lazy(u'App Price'),
                                   empty_label=None, required=False)
    currencies = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        required=False, label=_lazy(u'Supported Non-USD Currencies'))

    free_platforms = forms.MultipleChoiceField(
        choices=FREE_PLATFORMS, required=False)
    paid_platforms = forms.MultipleChoiceField(
        choices=PAID_PLATFORMS, required=False)

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        self.addon = kw.pop('addon')
        self.user = kw.pop('user')

        kw['initial'] = {
            'allow_inapp': self.addon.premium_type in amo.ADDON_INAPPS
        }
        if self.addon.premium:
            # If the app has a premium object, set the initial price.
            kw['initial']['price'] = self.addon.premium.price

        super(PremiumForm, self).__init__(*args, **kw)

        if self.addon.premium_type in amo.ADDON_PREMIUMS:
            # Require the price field if the app is premium.
            self.fields['price'].required = True

        # Get the list of supported devices and put them in the data.
        self.device_data = {}
        supported_devices = [amo.REVERSE_DEVICE_LOOKUP[dev.id] for dev in
                             self.addon.device_types]

        for platform in [x[0].split('-')[1] for x in
                         FREE_PLATFORMS + PAID_PLATFORMS]:
            supported = platform in supported_devices
            self.device_data['free-%s' % platform] = supported
            self.device_data['paid-%s' % platform] = supported

        choices = (PriceCurrency.objects.values_list('currency', flat=True)
                                        .distinct())
        self.fields['currencies'].choices = [(k, k) for k in choices if k]

        if (not self.initial.get('price') and
            len(self.fields['price'].choices) > 1):
            # Tier 0 (Free) should not be the default selection.
            self.initial['price'] = self._initial_price()

    def _initial_price(self):
        return Price.objects.active().exclude(price='0.00')[0]

    def clean_price(self):
        if (self.cleaned_data.get('premium_type') in amo.ADDON_PREMIUMS
            and not self.cleaned_data['price']):

            raise_required()

        return self.cleaned_data['price']

    def is_toggling(self):
        return self.request.POST.get('toggle-paid') or False

    def save(self):
        toggle = self.is_toggling()
        upsell = self.addon.upsold
        is_premium = self.addon.premium_type in amo.ADDON_PREMIUMS

        if toggle == 'paid' and self.addon.premium_type == amo.ADDON_FREE:
            # Toggle free apps to paid by giving them a premium object.
            premium = self.addon.premium
            if not premium:
                log.info('[1@%s] New AddonPremium object' % self.addon.pk)
                premium = AddonPremium()
                premium.addon = self.addon
            premium.price = self._initial_price()
            premium.save()

            self.addon.premium_type = amo.ADDON_PREMIUM
            self.addon.status = amo.STATUS_NULL

        elif toggle == 'free' and is_premium:
            # If the app is paid and we're making it free, remove it as an
            # upsell (if an upsell exists).
            upsell = self.addon.upsold
            if upsell:
                log.debug('[1@%s] Removing upsell; switching to free' %
                              self.addon.pk)
                upsell.delete()

            log.debug('[1@%s] Removing app payment account' % self.addon.pk)
            AddonPaymentAccount.objects.filter(addon=self.addon).delete()

            log.debug('[1@%s] Setting app premium_type to FREE' %
                          self.addon.pk)
            self.addon.premium_type = amo.ADDON_FREE

            if self.addon.status == amo.STATUS_NULL:
                # If the app was marked as incomplete because it didn't have a
                # payment account, mark it as either its highest status, or as
                # PENDING if it was never reviewed (highest_status == NULL).
                log.debug('[1@%s] Switching app to free, reverting incomplete '
                          'status to highest_status (%s) or pending if null.' %
                          (self.addon.pk, self.addon.highest_status))
                self.addon.status = (
                    self.addon.highest_status if
                    self.addon.highest_status != amo.STATUS_NULL else
                    amo.STATUS_PENDING)

        elif is_premium:
            # The dev is submitting updates for payment data about a paid app.
            self.addon.premium_type = (
                amo.ADDON_PREMIUM_INAPP if
                self.cleaned_data.get('allow_inapp') else amo.ADDON_PREMIUM)

            if 'price' in self.cleaned_data:
                log.debug('[1@%s] Updating app price (%s)' %
                          (self.addon.pk, self.cleaned_data['price']))
                self.addon.premium.price = self.cleaned_data['price']

            if 'currencies' in self.cleaned_data:
                log.debug('[1@%s] Updating app currencies (%s)' %
                          (self.addon.pk, self.cleaned_data['currencies']))
                self.addon.premium.currencies = self.cleaned_data['currencies']

            self.addon.premium.save()

        log.info('[1@%s] Saving app payment changes.' % self.addon.pk)
        self.addon.save()


class UpsellForm(happyforms.Form):

    upsell_of = AddonChoiceField(queryset=Addon.objects.none(), required=False,
                                 label=_lazy(u'This is a paid upgrade of'),
                                 empty_label=_lazy(u'Not an upgrade'))

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.user = kw.pop('user')

        kw.setdefault('initial', {})
        if self.addon.upsold:
            kw['initial']['upsell_of'] = self.addon.upsold.free

        super(UpsellForm, self).__init__(*args, **kw)

        self.fields['upsell_of'].queryset = (
            self.user.addons.exclude(pk=self.addon.pk,
                                     status=amo.STATUS_DELETED)
                            .filter(premium_type__in=amo.ADDON_FREES,
                                    type=self.addon.type))

    def save(self):
        current_upsell = self.addon.upsold
        new_upsell_app = self.cleaned_data.get('upsell_of')

        if new_upsell_app:
            # We're changing the upsell or creating a new one.

            if not current_upsell:
                # If the upsell is new or we just deleted the old upsell,
                # create a new upsell.
                log.debug('[1@%s] Creating app upsell' % self.addon.pk)
                current_upsell = AddonUpsell(premium=self.addon)

            # Set the upsell object to point to the app that we're upselling.
            current_upsell.free = new_upsell_app
            current_upsell.save()

        elif current_upsell:
            # We're deleting the upsell.
            log.debug('[1@%s] Deleting the app upsell' % self.addon.pk)
            current_upsell.delete()


class InappConfigForm(happyforms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(InappConfigForm, self).__init__(*args, **kwargs)
        if settings.INAPP_REQUIRE_HTTPS:
            self.fields['is_https'].widget.attrs['disabled'] = 'disabled'
            self.initial['is_https'] = True

    def clean_is_https(self):
        if settings.INAPP_REQUIRE_HTTPS:
            return True  # cannot override it with form values
        else:
            return self.cleaned_data['is_https']

    def clean_postback_url(self):
        return self._clean_relative_url(self.cleaned_data['postback_url'])

    def clean_chargeback_url(self):
        return self._clean_relative_url(self.cleaned_data['chargeback_url'])

    def _clean_relative_url(self, url):
        url = url.strip()
        if not url.startswith('/'):
            raise forms.ValidationError(
                _('This URL is relative to your app domain so it must start '
                  'with a slash.'))
        return url

    class Meta:
        model = InappConfig
        fields = ('postback_url', 'chargeback_url', 'is_https')


class PaypalSetupForm(happyforms.Form):
    email = forms.EmailField(required=False,
                             label=_lazy(u'PayPal email address'))

    def clean(self):
        data = self.cleaned_data
        if not data.get('email'):
            msg = _(u'The PayPal email is required.')
            self._errors['email'] = self.error_class([msg])

        return data


class PaypalPaymentData(happyforms.Form):
    first_name = forms.CharField(max_length=255, required=False)
    last_name = forms.CharField(max_length=255, required=False)
    full_name = forms.CharField(max_length=255, required=False)
    business_name = forms.CharField(max_length=255, required=False)
    country = forms.CharField(max_length=64)
    address_one = forms.CharField(max_length=255)
    address_two = forms.CharField(max_length=255,  required=False)
    post_code = forms.CharField(max_length=128, required=False)
    city = forms.CharField(max_length=128, required=False)
    state = forms.CharField(max_length=64, required=False)
    phone = forms.CharField(max_length=32, required=False)


def check_paypal_id(paypal_id):
    if not paypal_id:
        raise forms.ValidationError(
            _('PayPal ID required to accept contributions.'))
    try:
        valid, msg = paypal.check_paypal_id(paypal_id)
        if not valid:
            raise forms.ValidationError(msg)
    except socket.error:
        raise forms.ValidationError(_('Could not validate PayPal id.'))


# TODO: Figure out either a.) where to pull these from and implement that
# or b.) which constants file to move it to.
# TODO: Add more of these?
COUNTRIES = ['BRA', 'ESP']

class BangoPaymentAccountForm(happyforms.Form):

    bankAccountPayeeName = forms.CharField(
        max_length=50, label=_lazy(u'Account Holder Name'))
    companyName = forms.CharField(max_length=255, label=_lazy(u'Company Name'))
    vendorName = forms.CharField(max_length=255, label=_lazy(u'Vendor Name'))
    financeEmailAddress = forms.EmailField(
        required=False, label=_lazy(u'Financial Email'))
    adminEmailAddress = forms.EmailField(
        required=False, label=_lazy(u'Administrative Email'))

    address1 = forms.CharField(
        max_length=255, label=_lazy(u'Address'))
    address2 = forms.CharField(
        max_length=255, required=False, label=_lazy(u'Address 2'))
    addressCity = forms.CharField(
        max_length=128, label=_lazy(u'City/Municipality'))
    addressState = forms.CharField(
        max_length=64, label=_lazy(u'State/Province/Region'))
    addressZipCode = forms.CharField(
        max_length=128, label=_lazy(u'Zip/Postal Code'))
    addressPhone = forms.CharField(max_length=20, label=_lazy(u'Phone'))
    countryIso = forms.ChoiceField(label=_lazy(u'Country'))
    currencyIso = forms.ChoiceField(label=_lazy(u'Preferred Currency'))

    vatNumber = forms.CharField(
        max_length=17, required=False, label=_lazy(u'VAT Number'))

    bankAccountNumber = forms.CharField(
        max_length=20, required=False, label=_lazy(u'Bank Account Number'))
    bankAccountCode = forms.CharField(
        max_length=20, label=_lazy(u'Bank Account Code'))
    bankName = forms.CharField(max_length=50, label=_lazy(u'Bank Name'))
    bankAddress1 = forms.CharField(max_length=50, label=_lazy(u'Bank Address'))
    bankAddress2 = forms.CharField(
        max_length=50, required=False, label=_lazy(u'Bank Address 2'))
    bankAddressCity = forms.CharField(max_length=50, required=False,
                                      label=_lazy(u'Bank City/Municipality'))
    bankAddressState = forms.CharField(
        max_length=50, required=False,
        label=_lazy(u'Bank State/Province/Region'))
    bankAddressZipCode = forms.CharField(max_length=50,
                                         label=_lazy(u'Bank Zip/Postal Code'))
    bankAddressIso = forms.ChoiceField(label=_lazy(u'Bank Country'))

    account_name = forms.CharField(max_length=64, label=_(u'Account Name'))

    def __init__(self, *args, **kwargs):
        super(BangoPaymentAccountForm, self).__init__(*args, **kwargs)

        currency_choices = (
            PriceCurrency.objects.values_list('currency', flat=True)
                                 .distinct())
        self.fields['currencyIso'].choices = [('USD', 'USD')] + [
            (k, k) for k in filter(None, currency_choices)]

        country_choices = [(k, k) for k in COUNTRIES]
        self.fields['bankAddressIso'].choices = country_choices
        self.fields['countryIso'].choices = country_choices

    @property
    def happy_errors(self):
        return '\n'.join(u'<div><span>%u:</span> %u</div>' %
                             (field.label, field.errors)
                         for field in self if field.errors)


class BangoAccountListForm(happyforms.Form):
    accounts = forms.ModelChoiceField(
        queryset=PaymentAccount.objects.none(),
        label=_lazy(u'Payment Account'), required=False)

    def __init__(self, *args, **kwargs):
        self.addon = kwargs.pop('addon')
        user = kwargs.pop('user')

        super(BangoAccountListForm, self).__init__(*args, **kwargs)

        self.fields['accounts'].queryset = (
            PaymentAccount.objects.filter(user=user, inactive=False))

        try:
            current_account = AddonPaymentAccount.objects.get(addon=self.addon)
            self.initial['accounts'] = (
                PaymentAccount.objects.get(uri=current_account.account_uri))
            self.fields['accounts'].empty_label = None
        except (AddonPaymentAccount.DoesNotExist, PaymentAccount.DoesNotExist):
            pass

    def clean_accounts(self):
        if (AddonPaymentAccount.objects.filter(addon=self.addon).exists() and
            not self.cleaned_data.get('accounts')):

            raise forms.ValidationError(
                _('You cannot remove a payment account from an app.'))

        return self.cleaned_data.get('accounts')

    def save(self):
        if self.cleaned_data.get('accounts'):
            try:
                log.info('[1@%s] Deleting app payment account' % self.addon.pk)
                AddonPaymentAccount.objects.get(addon=self.addon).delete()
            except AddonPaymentAccount.DoesNotExist:
                pass

            log.info('[1@%s] Creating new app payment account' % self.addon.pk)
            AddonPaymentAccount.create(
                provider='bango', addon=self.addon,
                payment_account=self.cleaned_data['accounts'])

            # If the app is marked as paid and the information is complete
            # and the app is currently marked as incomplete, put it into the
            # re-review queue.
            if (self.addon.status == amo.STATUS_NULL and
                self.addon.highest_status == amo.STATUS_PUBLIC):
                # FIXME: This might cause noise in the future if bank accounts
                # get manually closed by Bango and we mark apps as STATUS_NULL
                # until a new account is selected. That will trigger a
                # re-review.

                log.info(u'[Webapp:%s] (Re-review) Public app, premium type '
                         u'upgraded.' % self.addon)
                RereviewQueue.flag(
                    self.addon, amo.LOG.REREVIEW_PREMIUM_TYPE_UPGRADE)

            self.addon.update(status=self.addon.highest_status)
