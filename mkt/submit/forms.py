import datetime

from django import forms

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy
import waffle

from addons.forms import AddonFormBasic
from addons.models import Addon, AddonUpsell
import amo
from apps.users.notifications import app_surveys
from apps.users.models import UserNotification
from files.models import FileUpload
from files.utils import parse_addon
from market.models import AddonPremium, Price
from translations.widgets import TransInput, TransTextarea
from translations.fields import TransField

from mkt.developers.forms import verify_app_domain
from mkt.site.forms import AddonChoiceField, APP_PUBLIC_CHOICES


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





class NewWebappForm(happyforms.Form):
    # The selections for free.
    FREE = (
        ('free-os', _lazy('Firefox OS')),
        ('free-desktop', _lazy('Firefox')),
        ('free-phone', _lazy('Firefox Mobile')),
        ('free-tablet', _lazy('Firefox Tablet')),
    )

    # The selections for paid.
    PAID = (
        ('paid-os', _lazy('Firefox OS')),
    )

    # Extra information about those values for display in the page.
    DEVICE_LOOKUP = {
        'free-os': _lazy('Fully open mobile ecosystem'),
        'free-desktop': _lazy('Windows, Mac and Linux'),
        'free-phone': _lazy('Android smartphones'),
        'free-tablet': _lazy('Android tablets'),
        'paid-os': _lazy('Fully open mobile ecosystem'),
    }

    ERRORS = {'both': _lazy(u'Cannot be free and paid.'),
              'none': _lazy(u'Please select a device.'),
              'packaged': _lazy(u'Packaged apps are only valid '
                                u'for Firefox OS.')}

    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy(u'There was an error with your'
                                                u' upload. Please try'
                                                u' again.')})

    packaged = forms.BooleanField(required=False)
    free = forms.MultipleChoiceField(choices=FREE, required=False)
    paid = forms.MultipleChoiceField(choices=PAID, required=False)


    def _add_error(self, msg):
        self._errors['free'] = self._errors['paid'] = self.ERRORS[msg]


    def _get_combined(self):
        return set(self.cleaned_data.get('free', []) +
                   self.cleaned_data.get('paid', []))

    def clean(self):
        data = self.cleaned_data

        # Check that they didn't select both.
        if data.get('free') and data.get('paid'):
            self._add_error('both')
            return

        # Check that they selected one.
        if not data.get('free') and not data.get('paid'):
            self._add_error('none')
            self._errors['free'] = self._errors['paid'] = self.ERRORS['none']
            return

        # Packaged apps are only valid for firefox os.
        if self.is_packaged():
            if not set(self._get_combined()).issubset(['paid-os', 'free-os']):
                self._add_error('packaged')
                return

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
                verify_app_domain(data['upload'].name)
            except forms.ValidationError, e:
                self._errors['upload'] = self.error_class(e.messages)
                return

        return data

    def get_devices(self):
        """Returns a device based on the requested free or paid."""
        platforms = {'os': amo.DEVICE_MOBILE,
                     'desktop': amo.DEVICE_DESKTOP,
                     'phone': amo.DEVICE_MOBILE,
                     'tablet': amo.DEVICE_TABLET}
        return [platforms[t.split('-', 1)[1]] for t in self._get_combined()]

    def get_paid(self):
        """Returns the premium type."""
        if self.cleaned_data.get('paid', False):
            return amo.ADDON_PREMIUM
        return amo.ADDON_FREE

    def is_packaged(self):
        return self.cleaned_data.get('packaged', False)

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon', None)
        super(NewWebappForm, self).__init__(*args, **kw)
        if not waffle.switch_is_active('allow-b2g-paid-submission'):
            del self.fields['paid']

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

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags', 'description',
                  'privacy_policy', 'homepage', 'support_url', 'support_email')
