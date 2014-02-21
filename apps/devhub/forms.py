# -*- coding: utf-8 -*-
import os
import re
import socket

from django import forms
from django.conf import settings
from django.db.models import Q
from django.forms.models import modelformset_factory
from django.forms.formsets import formset_factory, BaseFormSet
from django.utils.safestring import mark_safe
from django.utils.encoding import force_unicode

import commonware
import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy
from quieter_formset.formset import BaseModelFormSet
import waffle

from access import acl
import amo
import addons.forms
import paypal
from addons.models import (Addon, AddonDependency, AddonUser,
                           BlacklistedSlug, Charity, Preview)
from amo.forms import AMOModelForm
from amo.urlresolvers import reverse
from amo.utils import raise_required, slugify

from applications.models import Application, AppVersion
from files.models import File, FileUpload, Platform
from files.utils import parse_addon, VERSION_RE
from translations.widgets import TranslationTextarea, TranslationTextInput
from translations.fields import TransTextarea, TransField
from translations.models import delete_translation, Translation
from translations.forms import TranslationFormMixin
from versions.models import License, Version, ApplicationsVersions
from . import tasks

paypal_log = commonware.log.getLogger('z.paypal')


class AuthorForm(happyforms.ModelForm):
    class Meta:
        model = AddonUser
        exclude = ('addon',)


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
    reason = forms.CharField(required=False)

    def __init__(self, request):
        self.user = request.amo_user
        super(DeleteForm, self).__init__(request.POST)

    def clean_password(self):
        data = self.cleaned_data
        if not self.user.check_password(data['password']):
            raise forms.ValidationError(_('Password incorrect.'))


class LicenseChoiceRadio(forms.widgets.RadioFieldRenderer):

    def __iter__(self):
        for i, choice in enumerate(self.choices):
            yield LicenseRadioInput(self.name, self.value, self.attrs.copy(),
                                    choice, i)


class LicenseRadioInput(forms.widgets.RadioInput):

    def __init__(self, name, value, attrs, choice, index):
        super(LicenseRadioInput, self).__init__(name, value, attrs, choice,
                                                index)
        license = choice[1]  # Choice is a tuple (object.id, object).
        link = u'<a class="xx extra" href="%s" target="_blank">%s</a>'
        if hasattr(license, 'url'):
            details = link % (license.url, _('Details'))
            self.choice_label = mark_safe(self.choice_label + details)


class LicenseForm(AMOModelForm):
    builtin = forms.TypedChoiceField(choices=[], coerce=int,
                        widget=forms.RadioSelect(attrs={'class': 'license'},
                                                 renderer=LicenseChoiceRadio))
    name = forms.CharField(widget=TranslationTextInput(),
                           label=_lazy(u"What is your license's name?"),
                           required=False, initial=_('Custom License'))
    text = forms.CharField(widget=TranslationTextarea(), required=False,
                           label=_lazy(u'Provide the text of your license.'))

    def __init__(self, *args, **kw):
        addon = kw.pop('addon', None)
        self.version = None
        if addon:
            qs = addon.versions.order_by('-version')[:1]
            self.version = qs[0] if qs else None
            if self.version:
                kw['instance'], kw['initial'] = self.version.license, None
                # Clear out initial data if it's a builtin license.
                if getattr(kw['instance'], 'builtin', None):
                    kw['initial'] = {'builtin': kw['instance'].builtin}
                    kw['instance'] = None

        super(LicenseForm, self).__init__(*args, **kw)

        cs = [(x.builtin, x)
              for x in License.objects.builtins().filter(on_form=True)]
        cs.append((License.OTHER, _('Other')))
        self.fields['builtin'].choices = cs

    class Meta:
        model = License
        fields = ('builtin', 'name', 'text')

    def clean_name(self):
        name = self.cleaned_data['name']
        return name.strip() or _('Custom License')

    def clean(self):
        data = self.cleaned_data
        if self.errors:
            return data
        elif data['builtin'] == License.OTHER and not data['text']:
            raise forms.ValidationError(
                _('License text is required when choosing Other.'))
        return data

    def get_context(self):
        """Returns a view context dict having keys license_urls, license_form,
        and license_other_val.
        """
        license_urls = dict(License.objects.builtins()
                            .values_list('builtin', 'url'))
        return dict(license_urls=license_urls, version=self.version,
                    license_form=self.version and self,
                    license_other_val=License.OTHER)

    def save(self, *args, **kw):
        """Save all form data.

        This will only create a new license if it's not one of the builtin
        ones.

        Keyword arguments

        **log=True**
            Set to False if you do not want to log this action for display
            on the developer dashboard.
        """
        log = kw.pop('log', True)
        changed = self.changed_data

        builtin = self.cleaned_data['builtin']
        if builtin != License.OTHER:
            license = License.objects.get(builtin=builtin)
        else:
            # Save the custom license:
            license = super(LicenseForm, self).save(*args, **kw)

        if self.version:
            if changed or license != self.version.license:
                self.version.update(license=license)
                if log:
                    amo.log(amo.LOG.CHANGE_LICENSE, license,
                            self.version.addon)
        return license


class PolicyForm(TranslationFormMixin, AMOModelForm):
    """Form for editing the add-ons EULA and privacy policy."""
    has_eula = forms.BooleanField(required=False,
        label=_lazy(u'This add-on has an End-User License Agreement'))
    eula = TransField(widget=TransTextarea(), required=False,
        label=_lazy(u"Please specify your add-on's "
                    "End-User License Agreement:"))
    has_priv = forms.BooleanField(
        required=False, label=_lazy(u"This add-on has a Privacy Policy"))
    privacy_policy = TransField(widget=TransTextarea(), required=False,
        label=_lazy(u"Please specify your add-on's Privacy Policy:"))

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon', None)
        if not self.addon:
            raise ValueError('addon keyword arg cannot be None')
        kw['instance'] = self.addon
        kw['initial'] = dict(has_priv=self._has_field('privacy_policy'),
                             has_eula=self._has_field('eula'))
        super(PolicyForm, self).__init__(*args, **kw)

    def _has_field(self, name):
        # If there's a eula in any language, this addon has a eula.
        n = getattr(self.addon, u'%s_id' % name)
        return any(map(bool, Translation.objects.filter(id=n)))

    class Meta:
        model = Addon
        fields = ('eula', 'privacy_policy')

    def save(self, commit=True):
        ob = super(PolicyForm, self).save(commit)
        for k, field in (('has_eula', 'eula'),
                         ('has_priv', 'privacy_policy')):
            if not self.cleaned_data[k]:
                delete_translation(self.instance, field)

        if 'privacy_policy' in self.changed_data:
            amo.log(amo.LOG.CHANGE_POLICY, self.addon, self.instance)

        return ob


def ProfileForm(*args, **kw):
    # If the add-on takes contributions, then both fields are required.
    addon = kw['instance']
    fields_required = (kw.pop('required', False) or
                       bool(addon.takes_contributions))
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
    url = Charity._meta.get_field('url').formfield()

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


class AddonUploadForm(happyforms.Form):
    upload = forms.ModelChoiceField(widget=forms.HiddenInput,
        queryset=FileUpload.objects,
        error_messages={'invalid_choice': _lazy(u'There was an error with your '
                                                u'upload. Please try again.')})
    admin_override_validation = forms.BooleanField(
        required=False, label=_lazy(u'Override failed validation'))

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonUploadForm, self).__init__(*args, **kw)

    def _clean_upload(self):
        if not (self.cleaned_data['upload'].valid or
                self.cleaned_data['admin_override_validation'] and
                acl.action_allowed(self.request, 'ReviewerAdminTools', 'View')):
            raise forms.ValidationError(_(u'There was an error with your '
                                          u'upload. Please try again.'))

class NewAddonForm(AddonUploadForm):
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
            self._clean_upload()
            xpi = parse_addon(self.cleaned_data['upload'])
            addons.forms.clean_name(xpi['name'])
            self._clean_all_platforms()
        return self.cleaned_data

    def _clean_all_platforms(self):
        if (not self.cleaned_data['desktop_platforms']
            and not self.cleaned_data['mobile_platforms']):
            raise forms.ValidationError(_('Need at least one platform.'))


class NewVersionForm(NewAddonForm):
    nomination_type = forms.TypedChoiceField(
        choices=(
            ('', ''),
            (amo.STATUS_NOMINATED, _lazy('Full Review')),
            (amo.STATUS_UNREVIEWED, _lazy('Preliminary Review')),
        ),
        coerce=int, empty_value=None, required=False,
        error_messages={
            'required': _lazy(u'Please choose a review nomination type')
        })

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        super(NewVersionForm, self).__init__(*args, **kw)
        if self.addon.status == amo.STATUS_NULL:
            self.fields['nomination_type'].required = True

    def clean(self):
        if not self.errors:
            self._clean_upload()
            xpi = parse_addon(self.cleaned_data['upload'], self.addon)
            if self.addon.versions.filter(version=xpi['version']):
                raise forms.ValidationError(
                    _(u'Version %s already exists') % xpi['version'])
            self._clean_all_platforms()
        return self.cleaned_data


class NewFileForm(AddonUploadForm):
    platform = File._meta.get_field('platform').formfield(empty_label=None,
                    widget=forms.RadioSelect(attrs={'class': 'platform'}))
    platform.choices = sorted((p.id, p.name)
                              for p in amo.SUPPORTED_PLATFORMS.values())

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.version = kw.pop('version')
        super(NewFileForm, self).__init__(*args, **kw)
        # Reset platform choices to just those compatible with target app.
        field = self.fields['platform']
        field.choices = sorted((k, v.name) for k, v in
                               self.version.compatible_platforms().items())
        # Don't allow platforms we already have.
        to_exclude = set(File.objects.filter(version=self.version)
                                     .values_list('platform', flat=True))
        # Don't allow platform=ALL if we already have platform files.
        if len(to_exclude):
            to_exclude.add(amo.PLATFORM_ALL.id)

        # Always exclude PLATFORM_ALL_MOBILE because it's not supported for
        # downloads yet. The developer can choose Android + Maemo for now.
        # TODO(Kumar) Allow this option when it's supported everywhere.
        # See bug 646268.
        to_exclude.add(amo.PLATFORM_ALL_MOBILE.id)

        field.choices = [p for p in field.choices if p[0] not in to_exclude]
        field.queryset = Platform.objects.filter(id__in=dict(field.choices))

    def clean(self):
        if not self.version.is_allowed_upload():
            raise forms.ValidationError(
                _('You cannot upload any more files for this version.'))

        # Check for errors in the xpi.
        if not self.errors:
            xpi = parse_addon(self.cleaned_data['upload'], self.addon)
            if xpi['version'] != self.version.version:
                raise forms.ValidationError(_("Version doesn't match"))
        return self.cleaned_data


class FileForm(happyforms.ModelForm):
    platform = File._meta.get_field('platform').formfield(empty_label=None)

    class Meta:
        model = File
        fields = ('platform',)

    def __init__(self, *args, **kw):
        super(FileForm, self).__init__(*args, **kw)
        if kw['instance'].version.addon.type == amo.ADDON_SEARCH:
            del self.fields['platform']
        else:
            compat = kw['instance'].version.compatible_platforms()
            # TODO(Kumar) Allow PLATFORM_ALL_MOBILE when it's supported.
            # See bug 646268.
            if amo.PLATFORM_ALL_MOBILE.id in compat:
                del compat[amo.PLATFORM_ALL_MOBILE.id]
            pid = int(kw['instance'].platform_id)
            plats = [(p.id, p.name) for p in compat.values()]
            if pid not in compat:
                plats.append([pid, amo.PLATFORMS[pid].name])
            self.fields['platform'].choices = plats

    def clean_DELETE(self):
        if any(self.errors):
            return
        delete = self.cleaned_data['DELETE']

        if (delete and not self.instance.version.is_all_unreviewed):
            error = _('You cannot delete a file once the review process has '
                      'started.  You must delete the whole version.')
            raise forms.ValidationError(error)

        return delete


class BaseFileFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        files = [f.cleaned_data for f in self.forms
                 if not f.cleaned_data.get('DELETE', False)]

        if self.forms and 'platform' in self.forms[0].fields:
            platforms = [f['platform'].id for f in files]

            if amo.PLATFORM_ALL.id in platforms and len(files) > 1:
                raise forms.ValidationError(
                    _('The platform All cannot be combined '
                      'with specific platforms.'))

            if sorted(platforms) != sorted(set(platforms)):
                raise forms.ValidationError(
                    _('A platform can only be chosen once.'))


FileFormSet = modelformset_factory(File, formset=BaseFileFormSet,
                                   form=FileForm, can_delete=True, extra=0)


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


class AdminForm(happyforms.ModelForm):
    type = forms.ChoiceField(choices=amo.ADDON_TYPE.items())

    # Request is needed in other ajax forms so we're stuck here.
    def __init__(self, request=None, *args, **kw):
        super(AdminForm, self).__init__(*args, **kw)

    class Meta:
        model = Addon
        fields = ('trusted', 'type', 'guid',
                  'target_locale', 'locale_disambiguation')
        widgets = {
            'guid': forms.TextInput(attrs={'size': '50'})
        }


class InlineRadioRenderer(forms.widgets.RadioFieldRenderer):

    def render(self):
        return mark_safe(''.join(force_unicode(w) for w in self))


class PackagerBasicForm(forms.Form):
    name = forms.CharField(min_length=5, max_length=50,
        help_text=_lazy(u'Give your add-on a name. The most successful '
                        'add-ons give some indication of their function in '
                        'their name.'))
    description = forms.CharField(required=False, widget=forms.Textarea,
        help_text=_lazy(u'Briefly describe your add-on in one sentence. '
                        'This appears in the Add-ons Manager.'))
    version = forms.CharField(max_length=32,
        help_text=_lazy(u'Enter your initial version number. Depending on the '
                         'number of releases and your preferences, this is '
                         'usually 0.1 or 1.0'))
    id = forms.CharField(
        help_text=_lazy(u'Each add-on requires a unique ID in the form of a '
                        'UUID or an email address, such as '
                        'addon-name@developer.com. The email address does not '
                        'have to be valid.'))
    package_name = forms.CharField(min_length=5, max_length=50,
        help_text=_lazy(u'The package name of your add-on used within the '
                        'browser. This should be a short form of its name '
                        '(for example, Test Extension might be '
                        'test_extension).'))
    author_name = forms.CharField(
        help_text=_lazy(u'Enter the name of the person or entity to be '
                        'listed as the author of this add-on.'))
    contributors = forms.CharField(required=False, widget=forms.Textarea,
       help_text=_lazy(u'Enter the names of any other contributors to this '
                       'extension, one per line.'))

    def clean_name(self):
        name = self.cleaned_data['name']
        addons.forms.clean_name(name)
        name_regex = re.compile('(mozilla|firefox|thunderbird)', re.I)
        if name_regex.match(name):
            raise forms.ValidationError(
                _('Add-on names should not contain Mozilla trademarks.'))
        return name

    def clean_package_name(self):
        slug = self.cleaned_data['package_name']
        if slugify(slug, ok='_', lower=False, delimiter='_') != slug:
            raise forms.ValidationError(
                _('Enter a valid package name consisting of letters, numbers, '
                  'or underscores.'))
        if Addon.objects.filter(slug=slug).exists():
            raise forms.ValidationError(
                _('This package name is already in use.'))
        if BlacklistedSlug.blocked(slug):
            raise forms.ValidationError(
                _(u'The package name cannot be: %s.' % slug))
        return slug

    def clean_id(self):
        id_regex = re.compile(
                """(\{[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}\} |  # GUID
                   [a-z0-9-\.\+_]*\@[a-z0-9-\._]+)  # Email format""",
                re.I | re.X)

        if not id_regex.match(self.cleaned_data['id']):
            raise forms.ValidationError(
                _('The add-on ID must be a UUID string or an email '
                  'address.'))
        return self.cleaned_data['id']

    def clean_version(self):
        if not VERSION_RE.match(self.cleaned_data['version']):
            raise forms.ValidationError(_('The version string is invalid.'))
        return self.cleaned_data['version']


class PackagerCompatForm(forms.Form):
    enabled = forms.BooleanField(required=False)
    min_ver = forms.ModelChoiceField(AppVersion.objects.none(),
                                     empty_label=None, required=False,
                                     label=_lazy(u'Minimum'))
    max_ver = forms.ModelChoiceField(AppVersion.objects.none(),
                                     empty_label=None, required=False,
                                     label=_lazy(u'Maximum'))

    def __init__(self, *args, **kwargs):
        super(PackagerCompatForm, self).__init__(*args, **kwargs)
        if not self.initial:
            return

        self.app = self.initial['application']
        qs = (AppVersion.objects.filter(application=self.app.id)
                                .order_by('-version_int'))

        self.fields['enabled'].label = self.app.pretty
        if self.app == amo.FIREFOX:
            self.fields['enabled'].widget.attrs['checked'] = True

        # Don't allow version ranges as the minimum version.
        self.fields['min_ver'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max_ver'].queryset = qs.all()

        # Unreasonably hardcode a reasonable default minVersion.
        if self.app in (amo.FIREFOX, amo.MOBILE, amo.THUNDERBIRD):
            try:
                self.fields['min_ver'].initial = qs.filter(
                    version=amo.DEFAULT_MINVER)[0]
            except (IndexError, AttributeError):
                pass

    def clean_min_ver(self):
        if self.cleaned_data['enabled'] and not self.cleaned_data['min_ver']:
            raise_required()
        return self.cleaned_data['min_ver']

    def clean_max_ver(self):
        if self.cleaned_data['enabled'] and not self.cleaned_data['max_ver']:
            raise_required()
        return self.cleaned_data['max_ver']

    def clean(self):
        if self.errors:
            return

        data = self.cleaned_data

        if data['enabled']:
            min_ver = data['min_ver']
            max_ver = data['max_ver']
            if not (min_ver and max_ver):
                raise forms.ValidationError(_('Invalid version range.'))

            if min_ver.version_int > max_ver.version_int:
                raise forms.ValidationError(
                    _('Min version must be less than Max version.'))

            # Pass back the app name and GUID.
            data['min_ver'] = str(min_ver)
            data['max_ver'] = str(max_ver)
            data['name'] = self.app.pretty
            data['guid'] = self.app.guid

        return data


class PackagerCompatBaseFormSet(BaseFormSet):

    def __init__(self, *args, **kw):
        super(PackagerCompatBaseFormSet, self).__init__(*args, **kw)
        self.initial = [{'application': a} for a in amo.APP_USAGE]
        self._construct_forms()

    def clean(self):
        if any(self.errors):
            return
        if (not self.forms or not
            any(f.cleaned_data.get('enabled') for f in self.forms
                if f.app == amo.FIREFOX)):
            # L10n: {0} is Firefox.
            raise forms.ValidationError(
                _(u'{0} is a required target application.')
                .format(amo.FIREFOX.pretty))
        return self.cleaned_data


PackagerCompatFormSet = formset_factory(PackagerCompatForm,
    formset=PackagerCompatBaseFormSet, extra=0)


class PackagerFeaturesForm(forms.Form):
    about_dialog = forms.BooleanField(
            required=False,
            label=_lazy(u'About dialog'),
            help_text=_lazy(u'Creates a standard About dialog for your '
                            'extension'))
    preferences_dialog = forms.BooleanField(
            required=False,
            label=_lazy(u'Preferences dialog'),
            help_text=_lazy(u'Creates an example Preferences window'))
    toolbar = forms.BooleanField(
            required=False,
            label=_lazy(u'Toolbar'),
            help_text=_lazy(u'Creates an example toolbar for your extension'))
    toolbar_button = forms.BooleanField(
            required=False,
            label=_lazy(u'Toolbar button'),
            help_text=_lazy(u'Creates an example button on the browser '
                            'toolbar'))
    main_menu_command = forms.BooleanField(
            required=False,
            label=_lazy(u'Main menu command'),
            help_text=_lazy(u'Creates an item on the Tools menu'))
    context_menu_command = forms.BooleanField(
            required=False,
            label=_lazy(u'Context menu command'),
            help_text=_lazy(u'Creates a context menu item for images'))
    sidebar_support = forms.BooleanField(
            required=False,
            label=_lazy(u'Sidebar support'),
            help_text=_lazy(u'Creates an example sidebar panel'))


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
        w.attrs['data-url'] = reverse('devhub.compat_application_versions')

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


def DependencyFormSet(*args, **kw):
    addon_parent = kw.pop('addon')

    # Add-ons: Required add-ons cannot include apps nor personas.
    # Apps:    Required apps cannot include any add-ons.
    qs = (Addon.objects.reviewed().exclude(id=addon_parent.id).
          exclude(type__in=[amo.ADDON_PERSONA]))

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
                error = _('There cannot be more than 3 required add-ons.')
                raise forms.ValidationError(error)

    FormSet = modelformset_factory(AddonDependency, formset=_FormSet,
                                   form=_Form, extra=0, can_delete=True)
    return FormSet(*args, **kw)
