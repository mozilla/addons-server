import re

from django import forms

import happyforms

from addons.models import Addon
from amo.utils import slug_validator
from tower import ugettext as _
from translations.widgets import TranslationTextInput, TranslationTextarea


class AddonFormBasic(happyforms.ModelForm):
    name = forms.CharField(widget=TranslationTextInput, max_length=70)
    slug = forms.CharField(max_length=30)
    summary = forms.CharField(widget=TranslationTextarea, max_length=250)

    def clean_slug(self):
        target = self.cleaned_data['slug']
        slug_validator(target, lower=False)

        if self.cleaned_data['slug'] != self.instance.slug:
            if Addon.objects.filter(slug=target).exists():
                raise forms.ValidationError(_('This slug is already in use.'))
        return target


class AddonFormDetails(happyforms.ModelForm):
    description = forms.CharField(widget=TranslationTextarea)
    default_locale = forms.TypedChoiceField(choices=Addon.LOCALES)
    homepage = forms.URLField(widget=TranslationTextInput)

    class Meta:
        model = Addon
        fields = ('description', 'default_locale', 'homepage')


class AddonFormSupport(happyforms.ModelForm):
    support_url = forms.URLField(widget=TranslationTextInput)
    support_email = forms.EmailField(widget=TranslationTextInput)

    def save(self, addon, commit=False):
        instance = self.instance

        # If there's a GetSatisfaction URL entered, we'll extract the product
        # and company name and save it to the DB.
        gs_regex = "getsatisfaction\.com/(\w*)(?:/products/(\w*))?"
        match = re.search(gs_regex, instance.support_url.localized_string)

        company = product = None

        if match:
            company, product = match.groups()

        instance.get_satisfaction_company = company
        instance.get_satisfaction_product = product

        return super(AddonFormSupport, self).save()

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')


class AddonFormTechnical(forms.ModelForm):
    developer_comments = forms.CharField(widget=TranslationTextarea)

    class Meta:
        model = Addon
        fields = ('developer_comments', 'view_source', 'site_specific',
                  'external_software', 'binary')


class AddonForm(happyforms.ModelForm):
    name = forms.CharField(widget=TranslationTextInput,)
    homepage = forms.CharField(widget=TranslationTextInput,)
    eula = forms.CharField(widget=TranslationTextInput,)
    description = forms.CharField(widget=TranslationTextInput,)
    developer_comments = forms.CharField(widget=TranslationTextInput,)
    privacy_policy = forms.CharField(widget=TranslationTextInput,)
    the_future = forms.CharField(widget=TranslationTextInput,)
    the_reason = forms.CharField(widget=TranslationTextInput,)
    support_url = forms.CharField(widget=TranslationTextInput,)
    summary = forms.CharField(widget=TranslationTextInput,)
    support_email = forms.CharField(widget=TranslationTextInput,)

    class Meta:
        model = Addon
        fields = ('name', 'homepage', 'default_locale', 'support_email',
                  'support_url', 'description', 'summary',
                  'developer_comments', 'eula', 'privacy_policy', 'the_reason',
                  'the_future', 'view_source', 'prerelease', 'binary',
                  'site_specific', 'get_satisfaction_company',
                  'get_satisfaction_product',)

        exclude = ('status', )
