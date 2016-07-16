# -*- coding: utf-8 -*-
import json
import os
import socket

from django import forms
from django.conf import settings
from django.db.models import Q
from django.forms.models import modelformset_factory
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _, ugettext_lazy as _lazy

import commonware
from quieter_formset.formset import BaseModelFormSet

from olympia.access import acl
from olympia import amo, paypal
from olympia.addons.forms import AddonFormBasic
from olympia.addons.models import (
    Addon, AddonDependency, AddonUser, Charity, Preview)
from olympia.amo.forms import AMOModelForm
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.files.models import File, FileUpload
from olympia.files.utils import parse_addon
from olympia.lib import happyforms
from olympia.translations.widgets import (
    TranslationTextarea, TranslationTextInput)
from olympia.translations.fields import TransTextarea, TransField
from olympia.translations.models import delete_translation, Translation
from olympia.translations.forms import TranslationFormMixin
from olympia.versions.models import (
    ApplicationsVersions, License, VALID_SOURCE_EXTENSIONS, Version)

from . import tasks, utils


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
    slug = forms.CharField()
    reason = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.addon = kwargs.pop('addon')
        super(DeleteForm, self).__init__(*args, **kwargs)

    def clean_slug(self):
        data = self.cleaned_data
        if not data['slug'] == self.addon.slug:
            raise forms.ValidationError(_('Slug incorrect.'))


class AnnotateFileForm(happyforms.Form):
    message = forms.CharField()
    ignore_duplicates = forms.BooleanField(required=False)

    def clean_message(self):
        msg = self.cleaned_data['message']
        try:
            msg = json.loads(msg)
        except ValueError:
            raise forms.ValidationError(_('Invalid JSON object'))

        key = utils.ValidationComparator.message_key(msg)
        if key is None:
            raise forms.ValidationError(
                _('Message not eligible for annotation'))

        return msg


class LicenseRadioChoiceInput(forms.widgets.RadioChoiceInput):

    def __init__(self, name, value, attrs, choice, index):
        super(LicenseRadioChoiceInput, self).__init__(
            name, value, attrs, choice, index)
        license = choice[1]  # Choice is a tuple (object.id, object).
        link = u'<a class="xx extra" href="%s">%s</a>'
        if hasattr(license, 'url'):
            details = link % (license.url, _('Details'))
            self.choice_label = mark_safe(self.choice_label + details)


class LicenseRadioFieldRenderer(forms.widgets.RadioFieldRenderer):
    choice_input_class = LicenseRadioChoiceInput


class LicenseRadioSelect(forms.RadioSelect):
    renderer = LicenseRadioFieldRenderer


class LicenseForm(AMOModelForm):
    builtin = forms.TypedChoiceField(
        choices=[], coerce=int,
        widget=LicenseRadioSelect(attrs={'class': 'license'}))
    name = forms.CharField(widget=TranslationTextInput(),
                           label=_lazy(u"What is your license's name?"),
                           required=False, initial=_lazy('Custom License'))
    text = forms.CharField(widget=TranslationTextarea(), required=False,
                           label=_lazy(u'Provide the text of your license.'))

    def __init__(self, *args, **kw):
        addon = kw.pop('addon', None)
        self.version = None
        if addon:
            self.version = addon.latest_version
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
        if addon and not addon.is_listed:
            self.fields['builtin'].required = False

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
        if builtin == '':  # No license chosen, it must be an unlisted add-on.
            return
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
    has_eula = forms.BooleanField(
        required=False,
        label=_lazy(u'This add-on has an End-User License Agreement'))
    eula = TransField(
        widget=TransTextarea(), required=False,
        label=_lazy(u"Please specify your add-on's "
                    "End-User License Agreement:"))
    has_priv = forms.BooleanField(
        required=False, label=_lazy(u"This add-on has a Privacy Policy"))
    privacy_policy = TransField(
        widget=TransTextarea(), required=False,
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

    recipient = forms.ChoiceField(
        choices=RECIPIENTS,
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


class WithSourceMixin(object):
    def clean_source(self):
        source = self.cleaned_data.get('source')
        if source and not source.name.endswith(VALID_SOURCE_EXTENSIONS):
            raise forms.ValidationError(
                _('Unsupported file type, please upload an archive file '
                  '{extensions}.'.format(
                      extensions=VALID_SOURCE_EXTENSIONS))
            )
        return source


class SourceFileInput(forms.widgets.ClearableFileInput):
    """
    We need to customize the URL link.
    1. Remove %(initial)% from template_with_initial
    2. Prepend the new link (with customized text)
    """

    template_with_initial = '%(clear_template)s<br />%(input_text)s: %(input)s'

    def render(self, name, value, attrs=None):
        output = super(SourceFileInput, self).render(name, value, attrs)
        if value and hasattr(value, 'instance'):
            url = reverse('downloads.source', args=(value.instance.pk, ))
            params = {'url': url, 'output': output, 'label': _('View current')}
            output = '<a href="%(url)s">%(label)s</a> %(output)s' % params
        return output


class VersionForm(WithSourceMixin, happyforms.ModelForm):
    releasenotes = TransField(
        widget=TransTextarea(), required=False)
    approvalnotes = forms.CharField(
        widget=TranslationTextarea(attrs={'rows': 4}), required=False)
    source = forms.FileField(required=False, widget=SourceFileInput)

    class Meta:
        model = Version
        fields = ('releasenotes', 'approvalnotes', 'source')


class AppVersionChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.version


class CompatForm(happyforms.ModelForm):
    application = forms.TypedChoiceField(choices=amo.APPS_CHOICES,
                                         coerce=int,
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

        # After these changes, the foms need to be rebuilt. `forms`
        # is a cached property, so we delete the existing cache and
        # ask for a new one to be built.
        del self.forms
        self.forms

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


class AddonUploadForm(WithSourceMixin, happyforms.Form):
    upload = forms.ModelChoiceField(
        widget=forms.HiddenInput,
        queryset=FileUpload.objects,
        to_field_name='uuid',
        error_messages={
            'invalid_choice': _lazy(u'There was an error with your '
                                    u'upload. Please try again.')
        }
    )
    admin_override_validation = forms.BooleanField(
        required=False, label=_lazy(u'Override failed validation'))
    source = forms.FileField(required=False)
    is_manual_review = forms.BooleanField(
        initial=False, required=False,
        label=_lazy(u'Submit my add-on for manual review.'))

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonUploadForm, self).__init__(*args, **kw)

    def _clean_upload(self):
        if not (self.cleaned_data['upload'].valid or
                self.cleaned_data['upload'].validation_timeout or
                self.cleaned_data['admin_override_validation'] and
                acl.action_allowed(self.request, 'ReviewerAdminTools',
                                   'View')):
            raise forms.ValidationError(_(u'There was an error with your '
                                          u'upload. Please try again.'))


class NewAddonForm(AddonUploadForm):
    supported_platforms = forms.TypedMultipleChoiceField(
        choices=amo.SUPPORTED_PLATFORMS_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'platform'}),
        initial=[amo.PLATFORM_ALL.id],
        coerce=int,
        error_messages={'required': 'Need at least one platform.'}
    )
    is_unlisted = forms.BooleanField(
        initial=False,
        required=False,
        label=_lazy(u'Do not list my add-on on this site'),
        help_text=_lazy(
            u'Check this option if you intend to distribute your add-on on '
            u'your own and only need it to be signed by Mozilla.'))
    is_sideload = forms.BooleanField(
        initial=False,
        required=False,
        label=_lazy(u'This add-on will be bundled with an application '
                    u'installer.'),
        help_text=_lazy(u'Add-ons that are bundled with application '
                        u'installers will be code reviewed '
                        u'by Mozilla before they are signed and are held to a '
                        u'higher quality standard.'))

    def clean(self):
        if not self.errors:
            self._clean_upload()
            # parse and validate the add-on
            parse_addon(self.cleaned_data['upload'])
        return self.cleaned_data


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
    beta = forms.BooleanField(
        required=False,
        help_text=_lazy(u'A file with a version ending with '
                        u'a|alpha|b|beta|pre|rc and an optional number is '
                        u'detected as beta.'))

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        super(NewVersionForm, self).__init__(*args, **kw)
        if self.addon.status == amo.STATUS_NULL:
            self.fields['nomination_type'].required = True

    def clean(self):
        if not self.errors:
            self._clean_upload()
            xpi = parse_addon(self.cleaned_data['upload'], self.addon)
            # Make sure we don't already have the same non-rejected version.
            version_exists = Version.unfiltered.filter(
                addon=self.addon, version=xpi['version']).exists()
            if version_exists:
                msg = _(u'Version %s already exists, or was uploaded before.')
                raise forms.ValidationError(msg % xpi['version'])
        return self.cleaned_data


class NewFileForm(AddonUploadForm):
    platform = forms.TypedChoiceField(
        choices=amo.SUPPORTED_PLATFORMS_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'platform'}),
        coerce=int,
        # We don't want the id value of the field to be output to the user
        # when choice is invalid. Make a generic error message instead.
        error_messages={
            'invalid_choice': _lazy(u'Select a valid choice. That choice is '
                                    u'not one of the available choices.')
        }
    )
    beta = forms.BooleanField(
        required=False,
        help_text=_lazy(u'A file with a version ending with a|alpha|b|beta and'
                        u' an optional number is detected as beta.'))

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.version = kw.pop('version')
        super(NewFileForm, self).__init__(*args, **kw)
        # Reset platform choices to just those compatible with target app.
        field = self.fields['platform']
        field.choices = sorted((p.id, p.name) for p in
                               self.version.compatible_platforms().values())
        # Don't allow platforms we already have.
        to_exclude = set(File.objects.filter(version=self.version)
                                     .values_list('platform', flat=True))
        # Don't allow platform=ALL if we already have platform files.
        if len(to_exclude):
            to_exclude.add(amo.PLATFORM_ALL.id)

        field.choices = [p for p in field.choices if p[0] not in to_exclude]

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
    platform = File._meta.get_field('platform').formfield()

    class Meta:
        model = File
        fields = ('platform',)

    def __init__(self, *args, **kw):
        super(FileForm, self).__init__(*args, **kw)
        if kw['instance'].version.addon.type == amo.ADDON_SEARCH:
            del self.fields['platform']
        else:
            compat = kw['instance'].version.compatible_platforms()
            pid = int(kw['instance'].platform)
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
            platforms = [f['platform'] for f in files]

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
    _choices = [(k, Addon.STATUS_CHOICES[k]) for k in
                (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED)]
    review_type = forms.TypedChoiceField(
        choices=_choices, widget=forms.HiddenInput,
        coerce=int, empty_value=None,
        error_messages={'required': _lazy(u'A review type must be selected.')})


class Step3Form(AddonFormBasic):
    description = TransField(widget=TransTextarea, required=False)
    tags = None

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'description')


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
    _choices = [(k, v) for k, v in amo.ADDON_TYPE.items()
                if k != amo.ADDON_ANY]
    type = forms.ChoiceField(choices=_choices)

    # Request is needed in other ajax forms so we're stuck here.
    def __init__(self, request=None, *args, **kw):
        super(AdminForm, self).__init__(*args, **kw)

    class Meta:
        model = Addon
        fields = ('type', 'guid',
                  'target_locale', 'locale_disambiguation')
        widgets = {
            'guid': forms.TextInput(attrs={'size': '50'})
        }


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
        versions = AppVersion.objects.filter(application=app_id)
        return [(v.id, v.version) for v in versions]

    def clean_application(self):
        app_id = int(self.cleaned_data['application'])
        app = amo.APPS_IDS.get(app_id)
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
