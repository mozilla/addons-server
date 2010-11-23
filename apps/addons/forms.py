import re

from django import forms
from django.conf import settings

import happyforms
from tower import ugettext as _, ungettext as ngettext

import amo
import captcha.fields
from addons.models import Addon, ReverseNameLookup
from amo.utils import slug_validator
from applications.models import AppVersion
from tags.models import Tag
from translations.fields import TransField, TransTextarea
from translations.forms import TranslationFormMixin
from translations.widgets import TranslationTextInput


def clean_name(name, instance=None):
    id = ReverseNameLookup.get(name)

    # If we get an id and either there's no instance or the instance.id != id.
    if id and (not instance or id != instance.id):
        raise forms.ValidationError(_('This add-on name is already in use.  '
                                      'Please choose another.'))
    return name


class AddonFormBase(TranslationFormMixin, happyforms.ModelForm):

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonFormBase, self).__init__(*args, **kw)


class AddonFormBasic(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea, max_length=250)
    tags = forms.CharField(required=False)

    def __init__(self, *args, **kw):
        super(AddonFormBasic, self).__init__(*args, **kw)
        self.fields['tags'].initial = ', '.join(tag.tag_text for tag in
                                                self.instance.tags.all())
        # Do not simply append validators, as validators will persist between
        # instances.
        validate_name = lambda x: clean_name(x, self.instance)
        name_validators = list(self.fields['name'].validators)
        name_validators.append(validate_name)
        self.fields['name'].validators = name_validators

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


class AddonFormDetails(AddonFormBase):
    default_locale = forms.TypedChoiceField(choices=Addon.LOCALES)

    class Meta:
        model = Addon
        fields = ('description', 'default_locale', 'homepage')


class AddonFormSupport(AddonFormBase):
    support_url = TransField.adapt(forms.URLField)
    support_email = TransField.adapt(forms.EmailField)

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')

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


class AddonFormTechnical(AddonFormBase):
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

    def clean_name(self):
        name = self.cleaned_data['name']
        return clean_name(name)

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


beta_re = re.compile('(a|alpha|b|beta|pre|rc)\d*$')


class UpdateForm(happyforms.Form):
    reqVersion = forms.CharField(required=True)
    # Order is important, version validation requires an id.
    id = forms.ModelChoiceField(required=True,
                                to_field_name='guid',
                                queryset=Addon.objects.all())
    version = forms.CharField(required=True)
    appID = forms.CharField(required=True)
    # Order is important, appVersion validation requires an appID.
    appVersion = forms.CharField(required=True)
    appOS = forms.CharField(required=False)

    @property
    def addon(self):
        return self.cleaned_data.get('id')

    @property
    def is_beta_version(self):
        return beta_re.search(self.cleaned_data.get('version', ''))

    def clean_appOS(self):
        data = self.cleaned_data['appOS']
        for platform in [amo.PLATFORM_LINUX, amo.PLATFORM_BSD,
                 amo.PLATFORM_MAC, amo.PLATFORM_WIN,
                 amo.PLATFORM_SUN]:
            if platform.shortname in data:
                return platform

    def clean_appVersion(self):
        data = self.cleaned_data['appVersion']
        id = self.cleaned_data.get('appID', None)
        if not id:
            raise forms.ValidationError(_('AppID is required.'))
        try:
            app = AppVersion.objects.get(version=data,
                                         application__guid=id)
        except AppVersion.DoesNotExist:
            raise forms.ValidationError(_('Unknown version %s for app %s'
                                          % (data, id)))
        return app
