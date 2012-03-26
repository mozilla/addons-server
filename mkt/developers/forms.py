# -*- coding: utf-8 -*-
import os
import socket

from django import forms
from django.conf import settings
from django.forms.models import modelformset_factory

import commonware
import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy
from quieter_formset.formset import BaseModelFormSet
import waffle

import amo
import addons.forms
from addons.forms import clean_name, slug_validator
import paypal
from addons.models import (Addon, AddonUpsell, AddonUser, BlacklistedSlug,
                           Preview)
from amo.helpers import loc
from amo.utils import raise_required

from files.models import FileUpload
from market.models import AddonPremium, Price, AddonPaymentData
from mkt.site.forms import AddonChoiceField, APP_UPSELL_CHOICES
from mkt.payments.models import InappConfig
from translations.widgets import TransInput, TransTextarea
from translations.fields import TransField
from translations.models import Translation
from translations.forms import TranslationFormMixin
from mkt.webapps.models import Webapp
from . import tasks

paypal_log = commonware.log.getLogger('z.paypal')


class AuthorForm(happyforms.ModelForm):

    # TODO: Remove this whole __init__ when the 'allow-refund' flag goes away.
    def __init__(self, *args, **kwargs):
        super(AuthorForm, self).__init__(*args, **kwargs)
        self.fields['role'].choices = (
            (c, s) for c, s in amo.AUTHOR_CHOICES
            if c != amo.AUTHOR_ROLE_SUPPORT or
            waffle.switch_is_active('allow-refund'))

    def clean_user(self):
        user = self.cleaned_data['user']
        if not user.read_dev_agreement:
            raise forms.ValidationError(
                _('All authors must have read and agreed to the developer '
                  'agreement.'))

        return user

    class Meta:
        model = AddonUser
        exclude = ('addon')


class BaseModelFormSet(BaseModelFormSet):
    """
    Override the parent's is_valid to prevent deleting all forms.
    """

    def is_valid(self):
        # clean() won't get called in is_valid() if all the rows are getting
        # deleted. We can't allow deleting everything.
        rv = super(BaseModelFormSet, self).is_valid()
        return rv and not any(self.errors) and not bool(self.non_form_errors())


class BaseAuthorFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        # cleaned_data could be None if it's the empty extra form.
        data = filter(None, [f.cleaned_data for f in self.forms
                             if not f.cleaned_data.get('DELETE', False)])
        if not any(d['role'] == amo.AUTHOR_ROLE_OWNER for d in data):
            raise forms.ValidationError(_('Must have at least one owner.'))
        if not any(d['listed'] for d in data):
            raise forms.ValidationError(
                _('At least one author must be listed.'))
        users = [d['user'] for d in data]
        if sorted(users) != sorted(set(users)):
            raise forms.ValidationError(
                _('An author can only be listed once.'))


AuthorFormSet = modelformset_factory(AddonUser, formset=BaseAuthorFormSet,
                                     form=AuthorForm, can_delete=True, extra=0)


class DeleteForm(happyforms.Form):
    password = forms.CharField()

    def __init__(self, request):
        self.user = request.amo_user
        super(DeleteForm, self).__init__(request.POST)

    def clean_password(self):
        data = self.cleaned_data
        if not self.user.check_password(data['password']):
            raise forms.ValidationError(_('Password incorrect.'))


class InappConfigForm(happyforms.ModelForm):

    def clean_postback_url(self):
        return self._clean_relative_url(self.cleaned_data['postback_url'])

    def clean_chargeback_url(self):
        return self._clean_relative_url(self.cleaned_data['chargeback_url'])

    def _clean_relative_url(self, url):
        url = url.strip()
        if not url.startswith('/'):
            raise forms.ValidationError(_('This URL is relative to your app '
                                          'domain so it must start with a '
                                          'slash.'))
        return url

    class Meta:
        model = InappConfig
        fields = ('postback_url', 'chargeback_url')


def ProfileForm(*args, **kw):
    # If the add-on takes contributions, then both fields are required.
    addon = kw['instance']
    fields_required = (kw.pop('required', False) or
                       bool(addon.takes_contributions))
    if addon.is_webapp():
        the_reason_label = _('Why did you make this app?')
        the_future_label = _("What's next for this app?")
    else:
        the_reason_label = _('Why did you make this add-on?')
        the_future_label = _("What's next for this add-on?")

    class _Form(TranslationFormMixin, happyforms.ModelForm):
        the_reason = TransField(widget=TransTextarea(),
                                     required=fields_required,
                                     label=the_reason_label)
        the_future = TransField(widget=TransTextarea(),
                                     required=fields_required,
                                     label=the_future_label)

        class Meta:
            model = Addon
            fields = ('the_reason', 'the_future')

    return _Form(*args, **kw)


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


def verify_app_domain(manifest_url):
    if waffle.switch_is_active('webapps-unique-by-domain'):
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


class PreviewForm(happyforms.ModelForm):
    caption = TransField(widget=TransTextarea, required=False)
    file_upload = forms.FileField(required=False)
    upload_hash = forms.CharField(required=False)

    def save(self, addon, commit=True):
        if self.cleaned_data:
            self.instance.addon = addon
            if self.cleaned_data.get('DELETE'):
                # Existing preview.
                if self.instance.id:
                    self.instance.delete()
                # User has no desire to save this preview.
                return

            super(PreviewForm, self).save(commit=commit)
            if self.cleaned_data['upload_hash']:
                upload_hash = self.cleaned_data['upload_hash']
                upload_path = os.path.join(settings.TMP_PATH, 'preview',
                                           upload_hash)
                tasks.resize_preview.delay(upload_path, self.instance,
                                           set_modified_on=[self.instance])

    class Meta:
        model = Preview
        fields = ('caption', 'file_upload', 'upload_hash', 'id', 'position')


class BasePreviewFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return


PreviewFormSet = modelformset_factory(Preview, formset=BasePreviewFormSet,
                                      form=PreviewForm, can_delete=True,
                                      extra=1)


class NewManifestForm(happyforms.Form):
    manifest = forms.URLField(verify_exists=False)

    def clean_manifest(self):
        manifest = self.cleaned_data['manifest']
        verify_app_domain(manifest)
        return manifest


class PremiumForm(happyforms.Form):
    """
    The premium details for an addon, which is unfortunately
    distributed across a few models.
    """
    premium_type = forms.TypedChoiceField(coerce=lambda x: int(x),
                                choices=amo.ADDON_PREMIUM_TYPES.items(),
                                widget=forms.RadioSelect())
    price = forms.ModelChoiceField(queryset=Price.objects.active(),
                                   label=_('Add-on price'),
                                   empty_label=None,
                                   required=False)
    do_upsell = forms.TypedChoiceField(coerce=lambda x: bool(int(x)),
                                       choices=APP_UPSELL_CHOICES,
                                       widget=forms.RadioSelect(),
                                       required=False)
    free = AddonChoiceField(queryset=Addon.objects.none(),
                                  required=False,
                                  empty_label='')
    text = forms.CharField(widget=forms.Textarea(), required=False)
    support_email = forms.EmailField()

    def __init__(self, *args, **kw):
        self.extra = kw.pop('extra')
        self.request = kw.pop('request')
        self.addon = self.extra['addon']
        kw['initial'] = {
            'support_email': self.addon.support_email,
            'premium_type': self.addon.premium_type,
            'do_upsell': 0,
        }
        if self.addon.premium:
            kw['initial']['price'] = self.addon.premium.price

        upsell = self.addon.upsold
        if upsell:
            kw['initial'].update({
                'text': upsell.text,
                'free': upsell.free,
                'do_upsell': 1,
            })

        super(PremiumForm, self).__init__(*args, **kw)
        if self.addon.is_webapp():
            self.fields['price'].label = loc('App price')
            self.fields['do_upsell'].choices = APP_UPSELL_CHOICES
        self.fields['free'].queryset = (self.extra['amo_user'].addons
                                    .exclude(pk=self.addon.pk)
                                    .filter(premium_type__in=amo.ADDON_FREES,
                                            status__in=amo.VALID_STATUSES,
                                            type=self.addon.type))

        # For the wizard, we need to remove some fields.
        for field in self.extra.get('exclude', []):
            del self.fields[field]

    def clean_price(self):
        if (self.cleaned_data.get('premium_type') in amo.ADDON_PREMIUMS
            and not self.cleaned_data['price']):
            raise_required()
        return self.cleaned_data['price']

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

        self.addon.premium_type = self.cleaned_data['premium_type']
        self.addon.support_email = self.cleaned_data['support_email']
        self.addon.save()

        # If they checked later in the wizard and then decided they want
        # to keep it free, push to pending.
        if (not self.addon.paypal_id and self.addon.is_incomplete()
            and not self.addon.needs_paypal()):
            self.addon.mark_done()


class AppFormBasic(addons.forms.AddonFormBase):
    """Form to edit basic app info."""
    name = TransField(max_length=128, widget=TransInput)
    slug = forms.CharField(max_length=30, widget=forms.TextInput)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}),
                         max_length=250)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary')

    def __init__(self, *args, **kw):
        # Force the form to use app_slug if this is a webapp. We want to keep
        # this under "slug" so all the js continues to work.
        if kw['instance'].is_webapp():
            kw.setdefault('initial', {})['slug'] = kw['instance'].app_slug

        super(AppFormBasic, self).__init__(*args, **kw)
        # Do not simply append validators, as validators will persist between
        # instances.
        validate_name = lambda x: clean_name(x, self.instance)
        name_validators = list(self.fields['name'].validators)
        name_validators.append(validate_name)
        self.fields['name'].validators = name_validators

    def _post_clean(self):
        # Switch slug to app_slug in cleaned_data and self._meta.fields so
        # we can update the app_slug field for webapps.
        try:
            self._meta.fields = list(self._meta.fields)
            slug_idx = self._meta.fields.index('slug')
            data = self.cleaned_data
            if 'slug' in data:
                data['app_slug'] = data.pop('slug')
            self._meta.fields[slug_idx] = 'app_slug'
            super(AppFormBasic, self)._post_clean()
        finally:
            self._meta.fields[slug_idx] = 'slug'

    def clean_slug(self):
        target = self.cleaned_data['slug']
        slug_validator(target, lower=False)
        slug_field = 'app_slug' if self.instance.is_webapp() else 'slug'

        if target != getattr(self.instance, slug_field):
            if Addon.objects.filter(**{slug_field: target}).exists():
                raise forms.ValidationError(_('This slug is already in use.'))

            if BlacklistedSlug.blocked(target):
                raise forms.ValidationError(_('The slug cannot be: %s.'
                                              % target))
        return target

    def save(self, addon, commit=False):
        # We ignore `commit`, since we need it to be `False` so we can save
        # the ManyToMany fields on our own.
        addonform = super(AppFormBasic, self).save(commit=False)
        addonform.save()

        return addonform


class PaypalSetupForm(happyforms.Form):
    business_account = forms.ChoiceField(widget=forms.RadioSelect,
                                         choices=[],
                                         label="""Do you already have a PayPal
                                               Premier or Business account?""")
    email = forms.EmailField(required=False,
                             label='PayPal email address')

    def __init__(self, *args, **kw):
        super(PaypalSetupForm, self).__init__(*args, **kw)
        self.fields['business_account'].choices = (('yes', _lazy('Yes')),
                                                   ('no', _lazy('No')))

    def clean(self):
        data = self.cleaned_data
        if data.get('business_account') == 'yes' and not data.get('email'):
            msg = 'The PayPal email is required.'
            self._errors['email'] = self.error_class([msg])

        return data


class PaypalPaymentData(happyforms.ModelForm):

    class Meta:
        model = AddonPaymentData
        fields = ['first_name', 'last_name',
                  'address_one', 'address_two', 'city',
                  'state', 'post_code', 'country', 'phone']


class AppFormDetails(addons.forms.AddonFormBase):
    description = TransField(required=False,
        label=_(u'Provide a more detailed description of your app'),
        help_text=_(u'This description will appear on the details page.'),
        widget=TransTextarea)
    default_locale = forms.TypedChoiceField(required=False,
                                            choices=Addon.LOCALES)
    homepage = TransField.adapt(forms.URLField)(required=False,
                                                verify_exists=False)
    privacy_policy = TransField(widget=TransTextarea(), required=True,
        label=_lazy(u"Please specify your app's Privacy Policy"))

    class Meta:
        model = Addon
        fields = ('description', 'default_locale', 'homepage',
                  'privacy_policy')

    def clean(self):
        # Make sure we have the required translations in the new locale.
        required = 'name', 'summary', 'description'
        data = self.cleaned_data
        if not self.errors and 'default_locale' in self.changed_data:
            fields = dict((k, getattr(self.instance, k + '_id'))
                          for k in required)
            locale = self.cleaned_data['default_locale']
            ids = filter(None, fields.values())
            qs = (Translation.objects.filter(locale=locale, id__in=ids,
                                             localized_string__isnull=False)
                  .values_list('id', flat=True))
            missing = [k for k, v in fields.items() if v not in qs]
            # They might be setting description right now.
            if 'description' in missing and locale in data['description']:
                missing.remove('description')
            if missing:
                raise forms.ValidationError(
                    _('Before changing your default locale you must have a '
                      'name, summary, and description in that locale. '
                      'You are missing %s.') % ', '.join(map(repr, missing)))
        return data


class AppFormSupport(addons.forms.AddonFormBase):
    support_url = TransField.adapt(forms.URLField)(required=False,
                                                   verify_exists=False)
    support_email = TransField.adapt(forms.EmailField)()

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')

    def save(self, addon, commit=True):
        i = self.instance
        url = addon.support_url.localized_string
        (i.get_satisfaction_company,
         i.get_satisfaction_product) = addons.forms.get_satisfaction(url)
        return super(AppFormSupport, self).save(commit)
