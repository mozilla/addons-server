import datetime

from django import forms

import happyforms
import waffle
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from addons.forms import AddonFormBasic
from addons.models import Addon, AddonDeviceType, AddonUpsell
from apps.users.notifications import app_surveys
from apps.users.models import UserNotification
from editors.models import RereviewQueue
from files.models import FileUpload
from files.utils import parse_addon
from market.models import AddonPremium, Price
from translations.widgets import TransInput, TransTextarea
from translations.fields import TransField

from mkt.constants import DEVICE_LOOKUP, FREE_PLATFORMS, PAID_PLATFORMS
from mkt.site.forms import AddonChoiceField, APP_PUBLIC_CHOICES


def mark_for_rereview(addon, added_devices, removed_devices):
    msg = _(u'Device(s) changed: {0}').format(', '.join(
        [_(u'Added {0}').format(unicode(amo.DEVICE_TYPES[d].name))
         for d in added_devices] +
        [_(u'Removed {0}').format(unicode(amo.DEVICE_TYPES[d].name))
         for d in removed_devices]))
    RereviewQueue.flag(addon, amo.LOG.REREVIEW_DEVICES_ADDED, msg)


class DeviceTypeForm(happyforms.Form):
    ERRORS = {
        'both': _lazy(u'Cannot be free and paid.'),
        'none': _lazy(u'Please select a device.'),
        'packaged': _lazy(u'Packaged apps are valid for only Firefox OS.'),
    }

    free_platforms = forms.MultipleChoiceField(
        choices=FREE_PLATFORMS, required=False)
    paid_platforms = forms.MultipleChoiceField(
        choices=PAID_PLATFORMS, required=False)

    def save(self, addon, is_paid):
        data = self.cleaned_data[
            'paid_platforms' if is_paid else 'free_platforms']
        submitted_data = self.get_devices(t.split('-', 1)[1] for t in data)

        new_types = set(dev.id for dev in submitted_data)
        old_types = set(amo.DEVICE_TYPES[x.id].id for x in addon.device_types)

        added_devices = new_types - old_types
        removed_devices = old_types - new_types

        for d in added_devices:
            addon.addondevicetype_set.create(device_type=d)
        for d in removed_devices:
            addon.addondevicetype_set.filter(device_type=d).delete()

        # Send app to re-review queue if public and new devices are added.
        if added_devices and addon.status == amo.STATUS_PUBLIC:
            mark_for_rereview(addon, added_devices, removed_devices)

    def _add_error(self, msg):
        self._errors['free_platforms'] = self._errors['paid_platforms'] = (
            self.ERRORS[msg])

    def _get_combined(self):
        devices = (self.cleaned_data.get('free_platforms', []) +
                   self.cleaned_data.get('paid_platforms', []))
        return set(d.split('-', 1)[1] for d in devices)

    def clean(self):
        data = self.cleaned_data
        paid = data.get('paid_platforms', [])
        free = data.get('free_platforms', [])

        # Check that they didn't select both.
        if free and paid:
            self._add_error('both')
            return data

        # Check that they selected one.
        if not free and not paid:
            self._add_error('none')
            return data

        return super(DeviceTypeForm, self).clean()

    def get_devices(self, source=None):
        """Returns a device based on the requested free or paid."""
        if source is None:
            source = self._get_combined()

        platforms = {'firefoxos': amo.DEVICE_GAIA,
                     'desktop': amo.DEVICE_DESKTOP,
                     'android-mobile': amo.DEVICE_MOBILE,
                     'android-tablet': amo.DEVICE_TABLET}
        return map(platforms.get, source)

    def is_paid(self):
        return bool(self.cleaned_data.get('paid_platforms', False))

    def get_paid(self):
        """Returns the premium type. Should not be used if the form is used to
        modify an existing app.

        """

        return amo.ADDON_PREMIUM if self.is_paid() else amo.ADDON_FREE


class DevAgreementForm(happyforms.Form):
    read_dev_agreement = forms.BooleanField(label=_lazy(u'Agree and Continue'),
                                            widget=forms.HiddenInput)
    newsletter = forms.BooleanField(required=False, label=app_surveys.label,
                                    widget=forms.CheckboxInput)

    def __init__(self, *args, **kw):
        self.instance = kw.pop('instance')
        super(DevAgreementForm, self).__init__(*args, **kw)

    def save(self):
        self.instance.read_dev_agreement = datetime.datetime.now()
        self.instance.save()
        if self.cleaned_data.get('newsletter'):
            UserNotification.update_or_create(user=self.instance,
                notification_id=app_surveys.id, update={'enabled': True})


class NewWebappVersionForm(happyforms.Form):
    upload_error = _lazy(u'There was an error with your upload. '
                         u'Please try again.')
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': upload_error})

    def clean(self):
        data = self.cleaned_data
        if 'upload' not in self.cleaned_data:
            self._errors['upload'] = self.upload_error
            return

        # Packaged apps are only valid for firefox os.
        if self.is_packaged():
            # Now run the packaged app check, done in clean, because
            # clean_packaged needs to be processed first.
            try:
                pkg = parse_addon(data['upload'], self.addon)
            except forms.ValidationError, e:
                self._errors['upload'] = self.error_class(e.messages)
                return

            ver = pkg.get('version')
            if (ver and self.addon and
                self.addon.versions.filter(version=ver).exists()):
                self._errors['upload'] = _(u'Version %s already exists') % ver
                return
        else:
            # Throw an error if this is a dupe.
            # (JS sets manifest as `upload.name`.)
            try:
                from mkt.developers.forms import verify_app_domain
                verify_app_domain(data['upload'].name)
            except forms.ValidationError, e:
                self._errors['upload'] = self.error_class(e.messages)
                return

        return data

    def is_packaged(self):
        return self._is_packaged

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon', None)
        self._is_packaged = kw.pop('is_packaged', False)
        super(NewWebappVersionForm, self).__init__(*args, **kw)

        if (not waffle.switch_is_active('allow-b2g-paid-submission')
            and 'paid_platforms' in self.fields):
            del self.fields['paid_platforms']


class NewWebappForm(DeviceTypeForm, NewWebappVersionForm):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy(
            u'There was an error with your upload. Please try again.')})

    packaged = forms.BooleanField(required=False)

    def _add_error(self, msg):
        self._errors['free_platforms'] = self._errors['paid_platforms'] = (
            self.ERRORS[msg])

    def clean(self):
        data = super(NewWebappForm, self).clean()
        if not data:
            return

        if self.is_packaged() and 'firefoxos' not in self._get_combined():
            self._errors['free_platforms'] = self._errors['paid_platforms'] = (
                self.ERRORS['packaged'])
            return

        return data

    def is_packaged(self):
        return self._is_packaged or self.cleaned_data.get('packaged', False)

    def __init__(self, *args, **kw):
        super(NewWebappForm, self).__init__(*args, **kw)
        if not waffle.switch_is_active('allow-packaged-app-uploads'):
            del self.fields['packaged']


class PaypalSetupForm(happyforms.Form):
    business_account = forms.ChoiceField(widget=forms.RadioSelect, choices=[],
        label=_lazy(u'Do you already have a PayPal Premier '
                    'or Business account?'))
    email = forms.EmailField(required=False,
                             label=_lazy(u'PayPal email address'))

    def __init__(self, *args, **kw):
        super(PaypalSetupForm, self).__init__(*args, **kw)
        self.fields['business_account'].choices = (('yes', _lazy('Yes')),
            ('no', _lazy('No')),
            ('later', _lazy(u"I'll link my PayPal account later.")))

    def clean(self):
        data = self.cleaned_data
        if data.get('business_account') == 'yes' and not data.get('email'):
            msg = _(u'The PayPal email is required.')
            self._errors['email'] = self.error_class([msg])

        return data


class UpsellForm(happyforms.Form):
    price = forms.ModelChoiceField(queryset=Price.objects.active(),
                                   label=_lazy(u'App Price'),
                                   empty_label=None,
                                   required=True)
    make_public = forms.TypedChoiceField(choices=APP_PUBLIC_CHOICES,
                                    widget=forms.RadioSelect(),
                                    label=_lazy(u'When should your app be '
                                                 'made available for sale?'),
                                    coerce=int,
                                    required=False)
    free = AddonChoiceField(queryset=Addon.objects.none(),
                            required=False,
                            empty_label='',
                            label=_lazy(u'App to upgrade from'),
                            widget=forms.Select())

    def __init__(self, *args, **kw):
        self.extra = kw.pop('extra')
        self.request = kw.pop('request')
        self.addon = self.extra['addon']

        if 'initial' not in kw:
            kw['initial'] = {}

        kw['initial']['make_public'] = amo.PUBLIC_IMMEDIATELY
        if self.addon.premium:
            kw['initial']['price'] = self.addon.premium.price

        super(UpsellForm, self).__init__(*args, **kw)
        self.fields['free'].queryset = (self.extra['amo_user'].addons
                                    .exclude(pk=self.addon.pk)
                                    .filter(premium_type__in=amo.ADDON_FREES,
                                            status__in=amo.VALID_STATUSES,
                                            type=self.addon.type))

        if len(self.fields['price'].choices) > 1:
            # Tier 0 (Free) should not be the default selection.
            self.initial['price'] = (Price.objects.active()
                                     .exclude(price='0.00')[0])

    def clean_make_public(self):
        return (amo.PUBLIC_WAIT if self.cleaned_data.get('make_public')
                                else None)

    def save(self):
        if 'price' in self.cleaned_data:
            premium = self.addon.premium
            if not premium:
                premium = AddonPremium()
                premium.addon = self.addon
            premium.price = self.cleaned_data['price']
            premium.save()

        upsell = self.addon.upsold
        if self.cleaned_data['free']:

            # Check if this app was already a premium version for another app.
            if upsell and upsell.free != self.cleaned_data['free']:
                upsell.delete()

            if not upsell:
                upsell = AddonUpsell(premium=self.addon)
            upsell.free = self.cleaned_data['free']
            upsell.save()
        elif upsell:
            upsell.delete()

        self.addon.update(make_public=self.cleaned_data['make_public'])


class AppDetailsBasicForm(AddonFormBasic):
    """Form for "Details" submission step."""
    name = TransField(max_length=128,
                      widget=TransInput(attrs={'class': 'name l'}))
    slug = forms.CharField(max_length=30,
                           widget=forms.TextInput(attrs={'class': 'm'}))
    summary = TransField(max_length=250,
        label=_lazy(u"Brief Summary:"),
        help_text=_lazy(u'This summary will be shown in listings and '
                         'searches.'),
        widget=TransTextarea(attrs={'rows': 2, 'class': 'full'}))
    description = TransField(required=False,
        label=_lazy(u'Additional Information:'),
        help_text=_lazy(u'This description will appear on the details page.'),
        widget=TransTextarea(attrs={'rows': 4}))
    privacy_policy = TransField(widget=TransTextarea(attrs={'rows': 6}),
         label=_lazy(u'Privacy Policy:'),
         help_text=_lazy(u"A privacy policy that explains what "
                          "data is transmitted from a user's computer and how "
                          "it is used is required."))
    homepage = TransField.adapt(forms.URLField)(required=False,
        verify_exists=False, label=_lazy(u'Homepage:'),
        help_text=_lazy(u'If your app has another homepage, enter its address '
                         'here.'),
        widget=TransInput(attrs={'class': 'full'}))
    support_url = TransField.adapt(forms.URLField)(required=False,
        verify_exists=False, label=_lazy(u'Support Website:'),
        help_text=_lazy(u'If your app has a support website or forum, enter '
                         'its address here.'),
        widget=TransInput(attrs={'class': 'full'}))
    support_email = TransField.adapt(forms.EmailField)(
        label=_lazy(u'Support Email:'),
        help_text=_lazy(u'The email address used by end users to contact you '
                         'with support issues and refund requests.'),
        widget=TransInput(attrs={'class': 'full'}))
    flash = forms.TypedChoiceField(required=False,
        coerce=lambda x: bool(int(x)),
        label=_lazy(u'Does your app require Flash support?'),
        initial=0,
        choices=(
            (1, _lazy(u'Yes')),
            (0, _lazy(u'No')),
        ),
        widget=forms.RadioSelect)
    publish = forms.BooleanField(required=False, initial=1,
        label=_lazy(u"Publish my app in the Firefox Marketplace as soon as "
                     "it's reviewed."),
        help_text=_lazy(u"If selected your app will be published immediately "
                         "following its approval by reviewers.  If you don't "
                         "select this option you will be notified via email "
                         "about your app's approval and you will need to log "
                         "in and manually publish it."))

    class Meta:
        model = Addon
        fields = ('flash', 'name', 'slug', 'summary', 'tags', 'description',
                  'privacy_policy', 'homepage', 'support_url', 'support_email')

    def save(self, *args, **kw):
        uses_flash = self.cleaned_data.get('flash')
        af = self.instance.get_latest_file()
        if af is not None:
            af.update(uses_flash=bool(uses_flash))

        return super(AppDetailsBasicForm, self).save(*args, **kw)
