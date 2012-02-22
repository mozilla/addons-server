from django import forms
from django.conf import settings
from django.utils.safestring import mark_safe

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from addons.forms import AddonFormBasic
from addons.models import Addon
from files.models import FileUpload
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
                                widget=forms.RadioSelect())


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
