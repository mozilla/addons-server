from django import forms
from django.conf import settings
from django.utils.safestring import mark_safe

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

from addons.forms import AddonFormBasic
from addons.models import Addon, AddonUpsell
import amo
from amo.utils import raise_required
from files.models import FileUpload
from market.models import AddonPremium, Price
from mkt.site.forms import AddonChoiceField, APP_UPSELL_CHOICES
from translations.widgets import TransInput, TransTextarea
from translations.fields import TransField
from users.models import UserProfile
from webapps.models import Webapp


class DevAgreementForm(happyforms.ModelForm):
    read_dev_agreement = forms.BooleanField(
        label=mark_safe(_lazy('<b>Agree</b> and Continue')),
        widget=forms.HiddenInput)

    class Meta:
        model = UserProfile
        fields = ('read_dev_agreement',)


def verify_app_domain(manifest_url):
    if settings.WEBAPPS_UNIQUE_BY_DOMAIN:
        domain = Webapp.domain_from_url(manifest_url)
        if Webapp.objects.filter(app_domain=domain).exists():
            raise forms.ValidationError(
                _('An app already exists on this domain; '
                  'only one app per domain is allowed.'))


class NewWebappForm(happyforms.Form):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy('There was an error with your '
                                                'upload. Please try again.')})

    def clean_upload(self):
        upload = self.cleaned_data['upload']
        verify_app_domain(upload.name)  # JS puts manifest URL here.
        return upload


class PremiumTypeForm(happyforms.Form):
    premium_type = forms.TypedChoiceField(coerce=lambda x: int(x),
                                choices=amo.ADDON_PREMIUM_TYPES.items(),
                                widget=forms.RadioSelect(),
                                label=_lazy('Will your app use payments?'))


class UpsellForm(happyforms.Form):
    price = forms.ModelChoiceField(queryset=Price.objects.active(),
                                   label=_('App price'),
                                   empty_label=None,
                                   required=True)

    do_upsell = forms.TypedChoiceField(coerce=lambda x: bool(int(x)),
                                       choices=APP_UPSELL_CHOICES,
                                       widget=forms.RadioSelect(),
                                       label=_('Upsell this app'),
                                       required=False)
    free = AddonChoiceField(queryset=Addon.objects.none(),
                            required=False,
                            empty_label='',
                            label=_('App to upgrade from'),
                            widget=forms.Select())
    text = forms.CharField(widget=forms.Textarea(),
                           help_text=_('Describe the added benefits.'),
                           required=False,
                           label=_('Pitch your app'))

    def __init__(self, *args, **kw):
        self.extra = kw.pop('extra')
        self.request = kw.pop('request')
        self.addon = self.extra['addon']

        if self.addon.premium:
            kw['initial']['price'] = self.addon.premium.price

        super(UpsellForm, self).__init__(*args, **kw)
        self.fields['free'].queryset = (self.extra['amo_user'].addons
                                        .exclude(pk=self.addon.pk)
                                        .filter(premium_type=amo.ADDON_FREE,
                                                type=self.addon.type))

    def clean_text(self):
        if (self.cleaned_data['do_upsell']
            and not self.cleaned_data['text']):
            raise_required()
        return self.cleaned_data['text']

    def clean_free(self):
        if (self.cleaned_data['do_upsell']
            and not self.cleaned_data['free']):
            raise_required()
        return self.cleaned_data['free']

    def save(self):
        if 'price' in self.cleaned_data:
            premium = self.addon.premium
            if not premium:
                premium = AddonPremium()
                premium.addon = self.addon
            premium.price = self.cleaned_data['price']
            premium.save()

        upsell = self.addon.upsold
        if (self.cleaned_data['do_upsell'] and
            self.cleaned_data['text'] and self.cleaned_data['free']):

            # Check if this app was already a premium version for another app.
            if upsell and upsell.free != self.cleaned_data['free']:
                upsell.delete()

            if not upsell:
                upsell = AddonUpsell(premium=self.addon)
            upsell.text = self.cleaned_data['text']
            upsell.free = self.cleaned_data['free']
            upsell.save()
        elif not self.cleaned_data['do_upsell'] and upsell:
            upsell.delete()


class AppDetailsBasicForm(AddonFormBasic):
    """Form for "Details" submission step."""
    name = TransField(max_length=128,
                      widget=TransInput(attrs={'class': 'name l'}))
    slug = forms.CharField(max_length=30,
                           widget=forms.TextInput(attrs={'class': 'm'}))
    summary = TransField(max_length=250,
        label=_("Provide a brief summary of your app's functionality:"),
        help_text=_('This summary will be shown in listings and searches.'),
        widget=TransInput(attrs={'rows': 4, 'class': 'full'}))
    description = TransField(required=False,
        label=_('Provide a more detailed description of your app:'),
        help_text=_('This description will appear on the details page.'),
        widget=TransTextarea(attrs={'rows': 4}))
    privacy_policy = TransField(required=True,
        widget=TransTextarea(attrs={'rows': 6}),
        label=_lazy(u"Please specify your app's privacy policy:"))

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags', 'description',
                  'homepage', 'privacy_policy', 'support_email',
                  'support_url')
