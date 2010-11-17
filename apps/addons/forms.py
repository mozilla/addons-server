import re

from django import forms
from django.conf import settings

import happyforms

import amo
import captcha.fields
from addons.models import Addon
from amo.utils import slug_validator
from tower import ugettext as _
from translations.widgets import TranslationTextInput
from translations.fields import TransField, TransTextarea
from translations.forms import TranslationFormMixin


class AddonFormBasic(TranslationFormMixin, happyforms.ModelForm):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea, max_length=250)
    tags = forms.CharField(required=False)

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonFormBasic, self).__init__(*args, **kw)

        self.fields['tags'].initial = ', '.join(tag.tag_text for tag in
                                                self.instance.tags.all())

    def save(self, addon, commit=False):
        tags_new = self.cleaned_data['tags']
        tags_old = [t.tag_text for t in addon.tags.all()]

        # Add new tags.
        for t in set(tags_new) - set(tags_old):
            Tag(tag_text=t).save_tag(addon, self.request.amo_user)

        # Remove old tags.
        for t in set(tags_old) - set(tags_new):
            Tag(tag_text=t).remove_tag(addon, self.request.amo_user)

        return super(AddonFormBasic, self).save()

    def clean_tags(self):
        target = [t.strip() for t in self.cleaned_data['tags'].split(',')
                  if t.strip()]

        max_tags = amo.MAX_TAGS
        min_len = amo.MIN_TAG_LENGTH
        total = len(target)
        tags_short = [t for t in target if len(t.strip()) < min_len]

        if total > max_tags:
            raise forms.ValidationError(ngettext(
                                        'You have {0} too many tags.',
                                        'You have {0} too many tags.',
                                        total - max_tags)
                                        .format(total - max_tags))

        if tags_short:
            raise forms.ValidationError(ngettext(
                        'All tags must be at least {0} character.',
                        'All tags must be at least {0} characters.',
                        min_len).format(min_len))
        return target


    def clean_slug(self):
        target = self.cleaned_data['slug']
        slug_validator(target, lower=False)

        if self.cleaned_data['slug'] != self.instance.slug:
            if Addon.objects.filter(slug=target).exists():
                raise forms.ValidationError(_('This slug is already in use.'))
        return target


class AddonFormDetails(happyforms.ModelForm):
    default_locale = forms.TypedChoiceField(choices=Addon.LOCALES)

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonFormDetails, self).__init__(*args, **kw)

    class Meta:
        model = Addon
        fields = ('description', 'default_locale', 'homepage')


class AddonFormSupport(TranslationFormMixin, happyforms.ModelForm):
    support_url = TransField.adapt(forms.URLField)
    support_email = TransField.adapt(forms.EmailField)

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonFormSupport, self).__init__(*args, **kw)

    def save(self, addon, commit=True):
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

        return super(AddonFormSupport, self).save(commit)



class AddonFormTechnical(TranslationFormMixin, forms.ModelForm):
    developer_comments = TransField(widget=TransTextarea)

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

    def save(self):
        desc = self.data.get('description')
        if desc and desc != unicode(self.instance.description):
            amo.log(amo.LOG.EDIT_DESCRIPTIONS, self.instance)
        if self.changed_data:
            amo.log(amo.LOG.EDIT_PROPERTIES, self.instance)

        super(AddonForm, self).save()


class AbuseForm(happyforms.Form):
    recaptcha = captcha.fields.ReCaptchaField(label='')
    text = forms.CharField(required=True,
                           label='',
                           widget=forms.Textarea())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super(AbuseForm, self).__init__(*args, **kwargs)

        if (not self.request.user.is_anonymous() or
            not settings.RECAPTCHA_PRIVATE_KEY):
            del self.fields['recaptcha']
