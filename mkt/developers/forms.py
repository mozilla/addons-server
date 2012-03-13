# -*- coding: utf-8 -*-
import os
import socket

from django import forms
from django.conf import settings
from django.db.models import Q
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
from addons.models import (Addon, AddonDependency, AddonUpsell, AddonUser,
                           BlacklistedSlug, Charity, Preview)
from amo.helpers import loc
from amo.urlresolvers import reverse
from amo.utils import raise_required

from applications.models import Application, AppVersion
from files.models import FileUpload, Platform
from files.utils import parse_addon
from market.models import AddonPremium, Price, AddonPaymentData
from mkt.site.forms import AddonChoiceField, APP_UPSELL_CHOICES
from payments.models import InappConfig
from translations.widgets import TransInput, TransTextarea, TranslationTextarea
from translations.fields import TransField
from translations.models import Translation
from translations.forms import TranslationFormMixin
from versions.models import Version, ApplicationsVersions
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


class CharityForm(happyforms.ModelForm):
    url = Charity._meta.get_field('url').formfield(verify_exists=False)

    class Meta:
        model = Charity
        fields = ('name', 'url', 'paypal')

    def clean_paypal(self):
        check_paypal_id(self.cleaned_data['paypal'])
        return self.cleaned_data['paypal']

    def save(self, commit=True):
        # We link to the charity row in contrib stats, so we force all charity
        # changes to create a new row so we don't forget old charities.
        if self.changed_data and self.instance.id:
            self.instance.id = None
        return super(CharityForm, self).save(commit)


class ContribForm(TranslationFormMixin, happyforms.ModelForm):
    RECIPIENTS = (('dev', _lazy(u'The developers of this add-on')),
                  ('moz', _lazy(u'The Mozilla Foundation')),
                  ('org', _lazy(u'An organization of my choice')))

    recipient = forms.ChoiceField(choices=RECIPIENTS,
                    widget=forms.RadioSelect(attrs={'class': 'recipient'}))
    thankyou_note = TransField(widget=TransTextarea(), required=False)

    class Meta:
        model = Addon
        fields = ('paypal_id', 'suggested_amount', 'annoying',
                  'enable_thankyou', 'thankyou_note')
        widgets = {
            'annoying': forms.RadioSelect(),
            'suggested_amount': forms.TextInput(attrs={'class': 'short'}),
            'paypal_id': forms.TextInput(attrs={'size': '50'})
        }

    @staticmethod
    def initial(addon):
        if addon.charity:
            recip = 'moz' if addon.charity_id == amo.FOUNDATION_ORG else 'org'
        else:
            recip = 'dev'
        return {'recipient': recip,
                'annoying': addon.annoying or amo.CONTRIB_PASSIVE}

    def clean(self):
        if self.instance.upsell:
            raise forms.ValidationError(_('You cannot setup Contributions for '
                                    'an add-on that is linked to a premium '
                                    'add-on in the Marketplace.'))

        data = self.cleaned_data
        try:
            if not self.errors and data['recipient'] == 'dev':
                check_paypal_id(data['paypal_id'])
        except forms.ValidationError, e:
            self.errors['paypal_id'] = self.error_class(e.messages)
        # thankyou_note is a dict since it's a Translation.
        if not (data.get('enable_thankyou') and
                any(data.get('thankyou_note').values())):
            data['thankyou_note'] = {}
            data['enable_thankyou'] = False
        return data

    def clean_suggested_amount(self):
        amount = self.cleaned_data['suggested_amount']
        if amount is not None and amount <= 0:
            msg = _(u'Please enter a suggested amount greater than 0.')
            raise forms.ValidationError(msg)
        if amount > settings.MAX_CONTRIBUTION:
            msg = _(u'Please enter a suggested amount less than ${0}.').format(
                    settings.MAX_CONTRIBUTION)
            raise forms.ValidationError(msg)
        return amount


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


class VersionForm(happyforms.ModelForm):
    releasenotes = TransField(
        widget=TransTextarea(), required=False)
    approvalnotes = forms.CharField(
        widget=TranslationTextarea(attrs={'rows': 4}), required=False)

    class Meta:
        model = Version
        fields = ('releasenotes', 'approvalnotes')


class ApplicationChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.id


class AppVersionChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.version


class CompatForm(happyforms.ModelForm):
    application = ApplicationChoiceField(Application.objects.all(),
                                         widget=forms.HiddenInput)
    min = AppVersionChoiceField(AppVersion.objects.none())
    max = AppVersionChoiceField(AppVersion.objects.none())

    class Meta:
        model = ApplicationsVersions
        fields = ('application', 'min', 'max')

    def __init__(self, *args, **kw):
        super(CompatForm, self).__init__(*args, **kw)
        if self.initial:
            app = self.initial['application']
        else:
            app = self.data[self.add_prefix('application')]
        self.app = amo.APPS_ALL[int(app)]
        qs = AppVersion.objects.filter(application=app).order_by('version_int')
        self.fields['min'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max'].queryset = qs.all()

    def clean(self):
        min = self.cleaned_data.get('min')
        max = self.cleaned_data.get('max')
        if not (min and max and min.version_int <= max.version_int):
            raise forms.ValidationError(_('Invalid version range.'))
        return self.cleaned_data


class BaseCompatFormSet(BaseModelFormSet):

    def __init__(self, *args, **kw):
        super(BaseCompatFormSet, self).__init__(*args, **kw)
        # We always want a form for each app, so force extras for apps
        # the add-on does not already have.
        qs = kw['queryset'].values_list('application', flat=True)
        apps = [a for a in amo.APP_USAGE if a.id not in qs]
        self.initial = ([{} for _ in qs] +
                        [{'application': a.id} for a in apps])
        self.extra = len(amo.APP_GUIDS) - len(self.forms)
        self._construct_forms()

    def clean(self):
        if any(self.errors):
            return
        apps = filter(None, [f.cleaned_data for f in self.forms
                             if not f.cleaned_data.get('DELETE', False)])
        if not apps:
            raise forms.ValidationError(
                _('Need at least one compatible application.'))


CompatFormSet = modelformset_factory(
    ApplicationsVersions, formset=BaseCompatFormSet,
    form=CompatForm, can_delete=True, extra=0)


def verify_app_domain(manifest_url):
    if settings.WEBAPPS_UNIQUE_BY_DOMAIN:
        domain = Webapp.domain_from_url(manifest_url)
        if Addon.objects.filter(app_domain=domain).exists():
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
        verify_app_domain(upload.name)  # JS puts manifest URL here
        return upload


class NewAddonForm(happyforms.Form):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects.filter(valid=True),
        error_messages={'invalid_choice': _lazy('There was an error with your '
                                                'upload. Please try again.')})
    desktop_platforms = forms.ModelMultipleChoiceField(
            queryset=Platform.objects,
            widget=forms.CheckboxSelectMultiple(attrs={'class': 'platform'}),
            initial=[amo.PLATFORM_ALL.id],
            required=False)
    desktop_platforms.choices = ((p.id, p.name)
                                 for p in amo.DESKTOP_PLATFORMS.values())
    mobile_platforms = forms.ModelMultipleChoiceField(
            queryset=Platform.objects,
            widget=forms.CheckboxSelectMultiple(attrs={'class': 'platform'}),
            required=False)
    mobile_platforms.choices = ((p.id, p.name)
                                for p in amo.MOBILE_PLATFORMS.values())

    def clean(self):
        if not self.errors:
            xpi = parse_addon(self.cleaned_data['upload'])
            addons.forms.clean_name(xpi['name'])
            self._clean_all_platforms()
        return self.cleaned_data

    def _clean_all_platforms(self):
        if (not self.cleaned_data['desktop_platforms']
            and not self.cleaned_data['mobile_platforms']):
            raise forms.ValidationError(_('Need at least one platform.'))


class ReviewTypeForm(forms.Form):
    _choices = [(k, amo.STATUS_CHOICES[k]) for k in
                (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED)]
    review_type = forms.TypedChoiceField(
        choices=_choices, widget=forms.HiddenInput,
        coerce=int, empty_value=None,
        error_messages={'required': _lazy(u'A review type must be selected.')})


class Step3Form(addons.forms.AddonFormBasic):
    description = TransField(widget=TransTextarea, required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags', 'description',
                  'homepage', 'support_email', 'support_url')


class Step3WebappForm(Step3Form):
    """Form to override certain fields for webapps"""
    name = TransField(max_length=128)
    homepage = TransField.adapt(forms.URLField)(required=False,
                                                verify_exists=False)
    support_url = TransField.adapt(forms.URLField)(required=False,
                                                   verify_exists=False)
    support_email = TransField.adapt(forms.EmailField)(required=False)


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


class CheckCompatibilityForm(happyforms.Form):
    application = forms.ChoiceField(
                label=_lazy(u'Application'),
                choices=[(a.id, a.pretty) for a in amo.APP_USAGE])
    app_version = forms.ChoiceField(
                label=_lazy(u'Version'),
                choices=[('', _lazy(u'Select an application first'))])

    def __init__(self, *args, **kw):
        super(CheckCompatibilityForm, self).__init__(*args, **kw)
        w = self.fields['application'].widget
        # Get the URL after the urlconf has loaded.
        w.attrs['data-url'] = reverse(
            'mkt.developers.compat_application_versions')

    def version_choices_for_app_id(self, app_id):
        versions = AppVersion.objects.filter(application__id=app_id)
        return [(v.id, v.version) for v in versions]

    def clean_application(self):
        app_id = int(self.cleaned_data['application'])
        app = Application.objects.get(pk=app_id)
        self.cleaned_data['application'] = app
        choices = self.version_choices_for_app_id(app_id)
        self.fields['app_version'].choices = choices
        return self.cleaned_data['application']

    def clean_app_version(self):
        v = self.cleaned_data['app_version']
        return AppVersion.objects.get(pk=int(v))


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
    support_email = forms.EmailField(required=False)

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

    def clean_support_email(self):
        # Note: this can't be FREES, because Free + Premium should have
        # a support email.
        if (not self.cleaned_data.get('premium_type') == amo.ADDON_FREE
            and not self.cleaned_data['support_email']):
            raise_required()
        return self.cleaned_data['support_email']

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


def DependencyFormSet(*args, **kw):
    addon_parent = kw.pop('addon')

    # Add-ons: Required add-ons cannot include apps nor personas.
    # Apps:    Required apps cannot include any add-ons.
    qs = Addon.objects.reviewed().exclude(id=addon_parent.id)
    if addon_parent.is_webapp():
        qs = qs.filter(type=amo.ADDON_WEBAPP)
    else:
        qs = qs.exclude(type__in=[amo.ADDON_PERSONA, amo.ADDON_WEBAPP])

    class _Form(happyforms.ModelForm):
        addon = forms.CharField(required=False, widget=forms.HiddenInput)
        dependent_addon = forms.ModelChoiceField(qs, widget=forms.HiddenInput)

        class Meta:
            model = AddonDependency
            fields = ('addon', 'dependent_addon')

        def clean_addon(self):
            return addon_parent

    class _FormSet(BaseModelFormSet):

        def clean(self):
            if any(self.errors):
                return
            form_count = len([f for f in self.forms
                              if not f.cleaned_data.get('DELETE', False)])
            if form_count > 3:
                if addon_parent.is_webapp():
                    error = loc('There cannot be more than 3 required apps.')
                else:
                    error = _('There cannot be more than 3 required add-ons.')
                raise forms.ValidationError(error)

    FormSet = modelformset_factory(AddonDependency, formset=_FormSet,
                                   form=_Form, extra=0, can_delete=True)
    return FormSet(*args, **kw)


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
