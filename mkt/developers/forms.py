# -*- coding: utf-8 -*-
from datetime import datetime
import os
import socket

from django import forms
from django.conf import settings
from django.forms.models import modelformset_factory

import commonware
import happyforms
import waffle
from quieter_formset.formset import BaseModelFormSet
from tower import ugettext as _, ugettext_lazy as _lazy, ungettext as ngettext


import amo
import addons.forms
import paypal
from access import acl
from addons.forms import clean_name, icons, IconWidgetRenderer, slug_validator
from addons.models import (Addon, AddonCategory, AddonUpsell, AddonUser,
                           BlacklistedSlug, Category, Preview)
from addons.widgets import CategoriesSelectMultiple
from amo.utils import raise_required, remove_icons
from lib.video import tasks as vtasks
from market.models import AddonPremium, Price, PriceCurrency
from mkt.constants.ratingsbodies import (RATINGS_BY_NAME, ALL_RATINGS,
                                         RATINGS_BODIES)
from translations.fields import TransField
from translations.forms import TranslationFormMixin
from translations.models import Translation
from translations.widgets import TransInput, TransTextarea

import mkt
from mkt.inapp_pay.models import InappConfig
from mkt.reviewers.models import RereviewQueue
from mkt.site.forms import AddonChoiceField, APP_UPSELL_CHOICES
from mkt.webapps.models import AddonExcludedRegion, ContentRating, Webapp

from . import tasks

log = commonware.log.getLogger('mkt.developers')
paypal_log = commonware.log.getLogger('mkt.paypal')


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
            raise forms.ValidationError(_('This URL is relative to your app '
                                          'domain so it must start with a '
                                          'slash.'))
        return url

    class Meta:
        model = InappConfig
        fields = ('postback_url', 'chargeback_url', 'is_https')


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


def trap_duplicate(request, manifest_url):
    # See if this user has any other apps with the same manifest.
    owned = (request.user.get_profile().addonuser_set
             .filter(addon__manifest_url=manifest_url))
    if not owned:
        return
    try:
        app = owned[0].addon
    except Addon.DoesNotExist:
        return
    error_url = app.get_dev_url()
    msg = None
    if app.status == amo.STATUS_PUBLIC:
        msg = _(u'Oops, looks like you already submitted that manifest '
                 'for %s, which is currently public. '
                 '<a href="%s">Edit app</a>')
    elif app.status == amo.STATUS_PENDING:
        msg = _(u'Oops, looks like you already submitted that manifest '
                 'for %s, which is currently pending. '
                 '<a href="%s">Edit app</a>')
    elif app.status == amo.STATUS_NULL:
        msg = _(u'Oops, looks like you already submitted that manifest '
                 'for %s, which is currently incomplete. '
                 '<a href="%s">Resume app</a>')
    elif app.status == amo.STATUS_REJECTED:
        msg = _(u'Oops, looks like you already submitted that manifest '
                 'for %s, which is currently rejected. '
                 '<a href="%s">Edit app</a>')
    elif app.status == amo.STATUS_DISABLED:
        msg = _(u'Oops, looks like you already submitted that manifest '
                 'for %s, which is currently disabled by Mozilla. '
                 '<a href="%s">Edit app</a>')
    elif app.disabled_by_user:
        msg = _(u'Oops, looks like you already submitted that manifest '
                 'for %s, which is currently disabled. '
                 '<a href="%s">Edit app</a>')
    if msg:
        return msg % (app.name, error_url)


def verify_app_domain(manifest_url, exclude=None):
    if waffle.switch_is_active('webapps-unique-by-domain'):
        domain = Webapp.domain_from_url(manifest_url)
        qs = Webapp.objects.filter(app_domain=domain)
        if exclude:
            qs = qs.exclude(pk=exclude.pk)
        if qs.exists():
            raise forms.ValidationError(
                _('An app already exists on this domain; '
                  'only one app per domain is allowed.'))


class PreviewForm(happyforms.ModelForm):
    caption = TransField(widget=TransTextarea, required=False)
    file_upload = forms.FileField(required=False)
    upload_hash = forms.CharField(required=False)
    # This lets us POST the data URIs of the unsaved previews so we can still
    # show them if there were form errors.
    unsaved_image_data = forms.CharField(required=False,
                                         widget=forms.HiddenInput)
    unsaved_image_type = forms.CharField(required=False,
                                         widget=forms.HiddenInput)

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
                filetype = (os.path.splitext(upload_hash)[1][1:]
                                   .replace('-', '/'))
                if filetype in amo.VIDEO_TYPES:
                    self.instance.update(filetype=filetype)
                    vtasks.resize_video.delay(upload_path, self.instance,
                                              user=amo.get_user(),
                                              set_modified_on=[self.instance])
                else:
                    self.instance.update(filetype='image/png')
                    tasks.resize_preview.delay(upload_path, self.instance,
                                               set_modified_on=[self.instance])

    class Meta:
        model = Preview
        fields = ('caption', 'file_upload', 'upload_hash', 'id', 'position')


class AdminSettingsForm(PreviewForm):
    DELETE = forms.BooleanField(required=False)
    mozilla_contact = forms.EmailField(required=False)
    app_ratings = forms.MultipleChoiceField(
        required=False,
        choices=RATINGS_BY_NAME)
    flash = forms.BooleanField(required=False)

    class Meta:
        model = Preview
        fields = ('caption', 'file_upload', 'upload_hash', 'position')

    def __init__(self, *args, **kw):
        # Get the object for the app's promo `Preview` and pass it to the form.
        if kw.get('instance'):
            addon = kw.pop('instance')
            self.instance = addon
            self.promo = addon.get_promo()

        # Just consume the request - we don't care.
        kw.pop('request', None)

        super(AdminSettingsForm, self).__init__(*args, **kw)

        if self.instance:
            self.initial['mozilla_contact'] = addon.mozilla_contact

            rs = []
            for r in addon.content_ratings.all():
                rating = RATINGS_BODIES[r.ratings_body].ratings[r.rating]
                rs.append(ALL_RATINGS.index(rating))
            self.initial['app_ratings'] = rs
            self.initial['flash'] = addon.uses_flash

    def clean_caption(self):
        return '__promo__'

    def clean_position(self):
        return -1

    def save(self, addon, commit=True):
        if (self.cleaned_data.get('DELETE') and
            'upload_hash' not in self.changed_data and self.promo.id):
            self.promo.delete()
        elif self.promo and 'upload_hash' in self.changed_data:
            self.promo.delete()
        elif self.cleaned_data.get('upload_hash'):
            super(AdminSettingsForm, self).save(addon, True)

        contact = self.cleaned_data.get('mozilla_contact')
        if contact:
            addon.update(mozilla_contact=contact)
        ratings = self.cleaned_data.get('app_ratings')
        if ratings:
            before = set(addon.content_ratings.filter(rating__in=ratings)
                         .values_list('rating', flat=True))
            after = set(int(r) for r in ratings)
            addon.content_ratings.exclude(rating__in=after).delete()
            for i in after - before:
                r = ALL_RATINGS[i]
                ContentRating.objects.create(addon=addon, rating=r.id,
                                             ratings_body=r.ratingsbody.id)
        else:
            addon.content_ratings.all().delete()
        uses_flash = self.cleaned_data.get('flash')
        af = addon.get_latest_file()
        if af is not None:
            af.update(uses_flash=bool(uses_flash))
        return addon


class BasePreviewFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        at_least_one = False
        for form in self.forms:
            if (not form.cleaned_data.get('DELETE') and
                form.cleaned_data.get('upload_hash') is not None):
                at_least_one = True
        if not at_least_one:
            if waffle.switch_is_active('video-upload'):
                raise forms.ValidationError(_('You must upload at least one '
                                              'screenshot or video.'))
            else:
                raise forms.ValidationError(_('You must upload at least one '
                                              'screenshot.'))


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
    premium_type = forms.TypedChoiceField(label=_lazy(u'Premium Type'),
        coerce=lambda x: int(x), choices=amo.ADDON_PREMIUM_TYPES.items(),
        widget=forms.RadioSelect())
    price = forms.ModelChoiceField(queryset=Price.objects.active(),
                                   label=_lazy(u'App Price'),
                                   empty_label=None,
                                   required=False)
    do_upsell = forms.TypedChoiceField(coerce=lambda x: bool(int(x)),
                                       choices=APP_UPSELL_CHOICES,
                                       widget=forms.RadioSelect(),
                                       required=False)
    free = AddonChoiceField(queryset=Addon.objects.none(), required=False,
                            empty_label='')
    text = forms.CharField(widget=forms.Textarea(), required=False)

    def __init__(self, *args, **kw):
        self.extra = kw.pop('extra')
        self.request = kw.pop('request')
        self.addon = self.extra['addon']
        kw['initial'] = {
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
            self.fields['price'].label = _(u'App Price')
            self.fields['do_upsell'].choices = APP_UPSELL_CHOICES
        self.fields['free'].queryset = (self.extra['amo_user'].addons
                                    .exclude(pk=self.addon.pk)
                                    .filter(premium_type__in=amo.ADDON_FREES,
                                            status__in=amo.VALID_STATUSES,
                                            type=self.addon.type))
        if (not self.initial.get('price') and
            len(list(self.fields['price'].choices)) > 1):
            # Tier 0 (Free) should not be the default selection.
            self.initial['price'] = (Price.objects.active()
                                     .exclude(price='0.00')[0])

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

        # Check for free -> paid for already public apps.
        premium_type = self.cleaned_data['premium_type']
        if (self.addon.premium_type == amo.ADDON_FREE and
            premium_type in amo.ADDON_PREMIUMS and
            self.addon.status == amo.STATUS_PUBLIC):
            # Free -> paid for public apps trigger re-review.
            log.info(u'[Webapp:%s] (Re-review) Public app, free -> paid.' % (
                self.addon))
            RereviewQueue.flag(self.addon, amo.LOG.REREVIEW_FREE_TO_PAID)

        self.addon.premium_type = premium_type
        self.addon.save()

        # If they checked later in the wizard and then decided they want
        # to keep it free, push to pending.
        if (not self.addon.needs_paypal() and self.addon.is_incomplete()):
            self.addon.mark_done()


class AppFormBasic(addons.forms.AddonFormBase):
    """Form to edit basic app info."""
    name = TransField(max_length=128, widget=TransInput)
    slug = forms.CharField(max_length=30, widget=forms.TextInput)
    manifest_url = forms.URLField(verify_exists=False)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}),
                         max_length=250)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'manifest_url', 'summary')

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

    def clean_manifest_url(self):
        manifest_url = self.cleaned_data['manifest_url']
        # Only verify if manifest changed.
        if 'manifest_url' in self.changed_data:
            # Only Admins can edit the manifest_url.
            if not acl.action_allowed(self.request, 'Admin', '%'):
                return self.instance.manifest_url
            verify_app_domain(manifest_url, exclude=self.instance)
        return manifest_url

    def save(self, addon, commit=False):
        # We ignore `commit`, since we need it to be `False` so we can save
        # the ManyToMany fields on our own.
        addonform = super(AppFormBasic, self).save(commit=False)
        addonform.save()

        return addonform


class PaypalSetupForm(happyforms.Form):
    business_account = forms.ChoiceField(widget=forms.RadioSelect, choices=[],
        label=_lazy(u'Do you already have a PayPal Premier '
                     'or Business account?'))
    email = forms.EmailField(required=False,
                             label=_lazy(u'PayPal email address'))

    def __init__(self, *args, **kw):
        super(PaypalSetupForm, self).__init__(*args, **kw)
        self.fields['business_account'].choices = (('yes', _lazy(u'Yes')),
                                                   ('no', _lazy(u'No')))

    def clean(self):
        data = self.cleaned_data
        if data.get('business_account') == 'yes' and not data.get('email'):
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


class AppFormDetails(addons.forms.AddonFormBase):
    description = TransField(required=False,
        label=_lazy(u'Provide a more detailed description of your app'),
        help_text=_lazy(u'This description will appear on the details page.'),
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


class AppFormMedia(addons.forms.AddonFormBase):
    icon_type = forms.CharField(required=False,
        widget=forms.RadioSelect(renderer=IconWidgetRenderer, choices=[]))
    icon_upload_hash = forms.CharField(required=False)
    unsaved_icon_data = forms.CharField(required=False,
                                        widget=forms.HiddenInput)

    class Meta:
        model = Addon
        fields = ('icon_upload_hash', 'icon_type')

    def __init__(self, *args, **kwargs):
        super(AppFormMedia, self).__init__(*args, **kwargs)

        # Add icons here so we only read the directory when
        # AppFormMedia is actually being used.
        self.fields['icon_type'].widget.choices = icons()

    def save(self, addon, commit=True):
        if self.cleaned_data['icon_upload_hash']:
            upload_hash = self.cleaned_data['icon_upload_hash']
            upload_path = os.path.join(settings.TMP_PATH, 'icon', upload_hash)

            dirname = addon.get_icon_dir()
            destination = os.path.join(dirname, '%s' % addon.id)

            remove_icons(destination)
            tasks.resize_icon.delay(upload_path, destination,
                                    amo.ADDON_ICON_SIZES,
                                    set_modified_on=[addon])

        return super(AppFormMedia, self).save(commit)


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


class CurrencyForm(happyforms.Form):
    currencies = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple,
                                           required=False,
                                           label=_lazy(u'Other currencies'))

    def __init__(self, *args, **kw):
        super(CurrencyForm, self).__init__(*args, **kw)
        choices = (PriceCurrency.objects.values_list('currency', flat=True)
                                .distinct())
        self.fields['currencies'].choices = [(k, amo.PAYPAL_CURRENCIES[k])
                                              for k in choices if k]


class AppAppealForm(happyforms.Form):
    """
    If a developer's app is rejected he can make changes and request
    another review.
    """

    release_notes = forms.CharField(
        label=_lazy(u'Your comments'),
        required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kw):
        self.product = kw.pop('product', None)
        super(AppAppealForm, self).__init__(*args, **kw)

    def save(self):
        v = self.product.versions.order_by('-created')[0]
        v.releasenotes = self.cleaned_data['release_notes']
        v.save()
        amo.log(amo.LOG.EDIT_VERSION, v.addon, v)
        # Mark app as pending again.
        self.product.mark_done()
        return v


class RegionForm(forms.Form):
    regions = forms.MultipleChoiceField(required=False,
        label=_lazy(u'Choose at least one region your app will '
                     'be listed in:'),
        choices=mkt.regions.REGIONS_CHOICES_NAME[1:],
        widget=forms.CheckboxSelectMultiple,
        error_messages={'required':
            _lazy(u'You must select at least one region.')})
    other_regions = forms.BooleanField(required=False, initial=True,
        label=_lazy(u'Other and new regions'))

    def __init__(self, *args, **kw):
        self.product = kw.pop('product', None)
        super(RegionForm, self).__init__(*args, **kw)

        # If we have excluded regions, uncheck those.
        # Otherwise, default to everything checked.
        self.regions_before = (self.product.get_region_ids() or
            mkt.regions.REGION_IDS)

        # If we have future excluded regions, uncheck box.
        self.future_exclusions = self.product.addonexcludedregion.filter(
            region=mkt.regions.FUTURE.id)

        self.initial = {
            'regions': self.regions_before,
            'other_regions': not self.future_exclusions.exists()
        }

        # Games cannot be listed in Brazil without a content rating.
        self.disabled_regions = []
        games = Webapp.category('games')
        if (games and self.product.categories.filter(id=games.id).exists()
            and not self.product.content_ratings_in(mkt.regions.BR)):
            self.disabled_regions.append(mkt.regions.BR.id)

    def save(self):
        before = set(self.regions_before)
        after = set(map(int, self.cleaned_data['regions']))

        # Add new region exclusions.
        to_add = before - after
        for r in to_add:
            g, c = AddonExcludedRegion.objects.get_or_create(
                addon=self.product, region=r)
            if c:
                log.info(u'[Webapp:%s] Excluded from new region (%s).'
                         % (self.product, r))

        # Remove old region exclusions.
        to_remove = after - before
        for r in to_remove:
            self.product.addonexcludedregion.filter(region=r).delete()
            log.info(u'[Webapp:%s] No longer exluded from region (%s).'
                     % (self.product, r))

        if self.cleaned_data['other_regions']:
            # Developer wants to be visible in future regions, then
            # delete excluded regions.
            self.future_exclusions.delete()
            log.info(u'[Webapp:%s] No longer excluded from future regions.'
                     % self.product)
        else:
            # Developer does not want future regions, then
            # exclude all future apps.
            g, c = AddonExcludedRegion.objects.get_or_create(
                addon=self.product, region=mkt.regions.FUTURE.id)
            if c:
                log.info(u'[Webapp:%s] Excluded from future regions.'
                         % self.product)

        # Disallow games in Brazil without a rating.
        games = Webapp.category('games')
        if games:
            r = mkt.regions.BR

            if (self.product.categories.filter(id=games.id) and
                self.product.listed_in(r) and
                not self.product.content_ratings_in(r)):

                g, c = AddonExcludedRegion.objects.get_or_create(
                    addon=self.product, region=r.id)
                if c:
                    log.info(u'[Webapp:%s] Game excluded from new region '
                              '(%s).' % (self.product, r.id))


class CategoryForm(happyforms.Form):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP),
        widget=CategoriesSelectMultiple)

    def __init__(self, *args, **kw):
        self.request = kw.pop('request', None)
        self.product = kw.pop('product', None)
        super(CategoryForm, self).__init__(*args, **kw)

        self.cats_before = list(self.product.categories
                                .values_list('id', flat=True))

        self.initial['categories'] = self.cats_before

        # If this app is featured, category changes are forbidden.
        self.disabled = (
            not acl.action_allowed(self.request, 'Addons', 'Edit') and
            Webapp.featured(cat=self.cats_before)
        )

    def clean_categories(self):
        categories = self.cleaned_data['categories']
        total = categories.count()
        max_cat = amo.MAX_CATEGORIES

        if self.disabled:
            raise forms.ValidationError(
                _('Categories cannot be changed while your app is featured.'))

        if total > max_cat:
            # L10n: {0} is the number of categories.
            raise forms.ValidationError(ngettext(
                'You can have only {0} category.',
                'You can have only {0} categories.',
                max_cat).format(max_cat))

        return categories

    def save(self):
        after = list(self.cleaned_data['categories']
                     .values_list('id', flat=True))
        before = self.cats_before

        # Add new categories.
        to_add = set(after) - set(before)
        for c in to_add:
            AddonCategory.objects.create(addon=self.product, category_id=c)

        # Remove old categories.
        to_remove = set(before) - set(after)
        for c in to_remove:
            self.product.addoncategory_set.filter(category=c).delete()

        # Disallow games in Brazil without a rating.
        games = Webapp.category('games')
        if (games and self.product.listed_in(mkt.regions.BR) and
            not self.product.content_ratings_in(mkt.regions.BR)):

            r = mkt.regions.BR.id

            if games.id in to_add:
                g, c = AddonExcludedRegion.objects.get_or_create(
                    addon=self.product, region=r)
                if c:
                    log.info(u'[Webapp:%s] Game excluded from new region '
                              '(%s).' % (self.product, r))

            elif games.id in to_remove:
                self.product.addonexcludedregion.filter(region=r).delete()
                log.info(u'[Webapp:%s] Game no longer exluded from region '
                          '(%s).' % (self.product, r))


class DevAgreementForm(happyforms.Form):
    read_dev_agreement = forms.BooleanField(label=_lazy(u'Agree'),
                                            widget=forms.HiddenInput)

    def __init__(self, *args, **kw):
        self.instance = kw.pop('instance')
        super(DevAgreementForm, self).__init__(*args, **kw)

    def save(self):
        self.instance.read_dev_agreement = datetime.now()
        self.instance.save()
