# -*- coding: utf-8 -*-
import os

from django import forms
from django.conf import settings
from django.db.models import Q
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext, ugettext_lazy as _

import jinja2
import waffle

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.activity.utils import log_and_notify
from olympia.addons.forms import AddonFormBase
from olympia.addons.models import (
    Addon, AddonCategory, AddonDependency, AddonReviewerFlags, AddonUser,
    Preview)
from olympia.amo.fields import HttpHttpsOnlyURLField
from olympia.amo.forms import AMOModelForm
from olympia.amo.templatetags.jinja_helpers import mark_safe_lazy
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.constants.categories import CATEGORIES
from olympia.files.models import File, FileUpload
from olympia.files.utils import parse_addon
from olympia.translations.fields import TransField, TransTextarea
from olympia.translations.forms import TranslationFormMixin
from olympia.translations.models import Translation, delete_translation
from olympia.translations.widgets import (
    TranslationTextarea, TranslationTextInput)
from olympia.versions.models import (
    VALID_SOURCE_EXTENSIONS, ApplicationsVersions, License, Version)

from . import tasks


class AuthorForm(forms.ModelForm):
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
            raise forms.ValidationError(
                ugettext('Must have at least one owner.'))
        if not any(d['listed'] for d in data):
            raise forms.ValidationError(
                ugettext('At least one author must be listed.'))
        users = [d['user'] for d in data]
        if sorted(users) != sorted(set(users)):
            raise forms.ValidationError(
                ugettext('An author can only be listed once.'))


AuthorFormSet = modelformset_factory(AddonUser, formset=BaseAuthorFormSet,
                                     form=AuthorForm, can_delete=True, extra=0)


class DeleteForm(forms.Form):
    slug = forms.CharField()
    reason = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.addon = kwargs.pop('addon')
        super(DeleteForm, self).__init__(*args, **kwargs)

    def clean_slug(self):
        data = self.cleaned_data
        if not data['slug'] == self.addon.slug:
            raise forms.ValidationError(ugettext('Slug incorrect.'))


class LicenseRadioSelect(forms.RadioSelect):

    def get_context(self, name, value, attrs):
        context = super(LicenseRadioSelect, self).get_context(
            name, value, attrs)

        # Make sure the `class` is only set on the radio fields and
        # not on the `ul`. This avoids style issues among other things.
        # See https://github.com/mozilla/addons-server/issues/8902
        # and https://github.com/mozilla/addons-server/issues/8920
        del context['widget']['attrs']['class']

        return context

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        context = super(LicenseRadioSelect, self).create_option(
            name=name, value=value, label=label, selected=selected,
            index=index, subindex=subindex, attrs=attrs)

        link = (u'<a class="xx extra" href="%s" target="_blank" '
                u'rel="noopener noreferrer">%s</a>')
        license = self.choices[index][1]

        if hasattr(license, 'url') and license.url:
            details = link % (license.url, ugettext('Details'))
            context['label'] = mark_safe(
                unicode(context['label']) + ' ' + details)
        if hasattr(license, 'icons'):
            context['attrs']['data-cc'] = license.icons
        context['attrs']['data-name'] = unicode(license)
        return context


class LicenseForm(AMOModelForm):
    # Hack to restore behavior from pre Django 1.10 times.
    # Django 1.10 enabled `required` rendering for required widgets. That
    # wasn't the case before, this should be fixed properly but simplifies
    # the actual Django 1.11 deployment for now.
    # See https://github.com/mozilla/addons-server/issues/8912 for proper fix.
    use_required_attribute = False

    builtin = forms.TypedChoiceField(
        choices=[], coerce=int,
        widget=LicenseRadioSelect(attrs={'class': 'license'}))
    name = forms.CharField(widget=TranslationTextInput(),
                           label=_(u'What is your license\'s name?'),
                           required=False, initial=_('Custom License'))
    text = forms.CharField(widget=TranslationTextarea(), required=False,
                           label=_(u'Provide the text of your license.'))

    def __init__(self, *args, **kwargs):
        self.version = kwargs.pop('version', None)
        if self.version:
            kwargs['instance'], kwargs['initial'] = self.version.license, None
            # Clear out initial data if it's a builtin license.
            if getattr(kwargs['instance'], 'builtin', None):
                kwargs['initial'] = {'builtin': kwargs['instance'].builtin}
                kwargs['instance'] = None
            self.cc_licenses = kwargs.pop(
                'cc', self.version.addon.type == amo.ADDON_STATICTHEME)
        else:
            self.cc_licenses = kwargs.pop(
                'cc', False)

        super(LicenseForm, self).__init__(*args, **kwargs)
        licenses = License.objects.builtins(
            cc=self.cc_licenses).filter(on_form=True)
        cs = [(x.builtin, x) for x in licenses]
        if not self.cc_licenses:
            # creative commons licenses don't have an 'other' option.
            cs.append((License.OTHER, ugettext('Other')))
        self.fields['builtin'].choices = cs
        if (self.version and
                self.version.channel == amo.RELEASE_CHANNEL_UNLISTED):
            self.fields['builtin'].required = False

    class Meta:
        model = License
        fields = ('builtin', 'name', 'text')

    def clean_name(self):
        name = self.cleaned_data['name']
        return name.strip() or ugettext('Custom License')

    def clean(self):
        data = self.cleaned_data
        if self.errors:
            return data
        elif data['builtin'] == License.OTHER and not data['text']:
            raise forms.ValidationError(
                ugettext('License text is required when choosing Other.'))
        return data

    def get_context(self):
        """Returns a view context dict having keys license_form,
        and license_other_val.
        """
        return {
            'version': self.version,
            'license_form': self.version and self,
            'license_other_val': License.OTHER
        }

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
        is_other = builtin == License.OTHER
        if not is_other:
            # We're dealing with a builtin license, there is no modifications
            # allowed to it, just return it.
            license = License.objects.get(builtin=builtin)
        else:
            # We're not dealing with a builtin license, so save it to the
            # database.
            license = super(LicenseForm, self).save(*args, **kw)

        if self.version:
            if (changed and is_other) or license != self.version.license:
                self.version.update(license=license)
                if log:
                    ActivityLog.create(amo.LOG.CHANGE_LICENSE, license,
                                       self.version.addon)
        return license


class PolicyForm(TranslationFormMixin, AMOModelForm):
    """Form for editing the add-ons EULA and privacy policy."""
    has_eula = forms.BooleanField(
        required=False,
        label=_(u'This add-on has an End-User License Agreement'))
    eula = TransField(
        widget=TransTextarea(), required=False,
        label=_(u'Please specify your add-on\'s '
                u'End-User License Agreement:'))
    has_priv = forms.BooleanField(
        required=False, label=_(u'This add-on has a Privacy Policy'),
        label_suffix='')
    privacy_policy = TransField(
        widget=TransTextarea(), required=False,
        label=_(u'Please specify your add-on\'s Privacy Policy:'))

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
            ActivityLog.create(amo.LOG.CHANGE_POLICY, self.addon,
                               self.instance)

        return ob


class WithSourceMixin(object):
    def clean_source(self):
        source = self.cleaned_data.get('source')
        if source and not source.name.endswith(VALID_SOURCE_EXTENSIONS):
            raise forms.ValidationError(
                ugettext(
                    'Unsupported file type, please upload an archive '
                    'file {extensions}.'.format(
                        extensions=VALID_SOURCE_EXTENSIONS)))
        return source


class SourceFileInput(forms.widgets.ClearableFileInput):
    """
    Like ClearableFileInput but with custom link URL and text for the initial
    data. Uses a custom template because django's is not flexible enough for
    our needs.
    """
    initial_text = _('View current')
    template_name = 'devhub/addons/includes/source_file_input.html'

    def get_context(self, name, value, attrs):
        context = super(SourceFileInput, self).get_context(name, value, attrs)
        if value and hasattr(value, 'instance'):
            context['download_url'] = reverse(
                'downloads.source', args=(value.instance.pk, ))
        return context


class VersionForm(WithSourceMixin, forms.ModelForm):
    releasenotes = TransField(
        widget=TransTextarea(), required=False)
    approvalnotes = forms.CharField(
        widget=TranslationTextarea(attrs={'rows': 4}), required=False)
    source = forms.FileField(required=False, widget=SourceFileInput)
    clear_pending_info_request = forms.BooleanField(required=False)

    class Meta:
        model = Version
        fields = ('releasenotes', 'clear_pending_info_request',
                  'approvalnotes', 'source',)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super(VersionForm, self).__init__(*args, **kwargs)
        # Fetch latest reviewer comment if the addon has a pending info
        # request,  so that the template in which the form is used can display
        # that comment.
        if self.instance and self.instance.addon.pending_info_request:
            try:
                self.pending_info_request_comment = (
                    ActivityLog.objects.for_addons(self.instance.addon)
                               .filter(action=amo.LOG.REQUEST_INFORMATION.id)
                               .latest('pk')).details['comments']
            except (ActivityLog.DoesNotExist, KeyError):
                self.pending_info_request_comment = ''

    def save(self, *args, **kwargs):
        super(VersionForm, self).save(*args, **kwargs)
        # Clear pending info request on the addon if requested, adding an entry
        # in the Activity Log to indicate that.
        if self.cleaned_data.get('clear_pending_info_request'):
            AddonReviewerFlags.objects.update_or_create(
                addon=self.instance.addon,
                defaults={'pending_info_request': None})
            log_and_notify(
                amo.LOG.DEVELOPER_CLEAR_INFO_REQUEST, None,
                self.request.user, self.instance)


class AppVersionChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.version


class CompatForm(forms.ModelForm):
    application = forms.TypedChoiceField(choices=amo.APPS_CHOICES,
                                         coerce=int,
                                         widget=forms.HiddenInput)
    min = AppVersionChoiceField(AppVersion.objects.none())
    max = AppVersionChoiceField(AppVersion.objects.none())

    class Meta:
        model = ApplicationsVersions
        fields = ('application', 'min', 'max')

    def __init__(self, *args, **kwargs):
        # 'version' should always be passed as a kwarg to this form. If it's
        # absent, it probably means form_kwargs={'version': version} is missing
        # from the instantiation of the formset.
        version = kwargs.pop('version')
        super(CompatForm, self).__init__(*args, **kwargs)
        if self.initial:
            app = self.initial['application']
        else:
            app = self.data[self.add_prefix('application')]
        self.app = amo.APPS_ALL[int(app)]
        qs = AppVersion.objects.filter(application=app).order_by('version_int')

        # Legacy extensions can't set compatibility higher than 56.* for
        # Firefox and Firefox for Android.
        # This does not concern Mozilla Signed Legacy extensions which
        # are shown the same version choice as WebExtensions.
        if (self.app in (amo.FIREFOX, amo.ANDROID) and
                not version.is_webextension and
                not version.is_mozilla_signed and
                version.addon.type not in amo.NO_COMPAT + (amo.ADDON_LPAPP,)):
            qs = qs.filter(version_int__lt=57000000000000)
        self.fields['min'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max'].queryset = qs.all()

    def clean(self):
        min = self.cleaned_data.get('min')
        max = self.cleaned_data.get('max')
        if not (min and max and min.version_int <= max.version_int):
            raise forms.ValidationError(ugettext('Invalid version range.'))
        return self.cleaned_data


class BaseCompatFormSet(BaseModelFormSet):

    def __init__(self, *args, **kwargs):
        super(BaseCompatFormSet, self).__init__(*args, **kwargs)
        # We always want a form for each app, so force extras for apps
        # the add-on does not already have.
        version = self.form_kwargs.get('version')
        static_theme = version and version.addon.type == amo.ADDON_STATICTHEME
        if static_theme:
            available_apps = amo.APP_USAGE_STATICTHEME
        elif waffle.switch_is_active('disallow-thunderbird-and-seamonkey'):
            available_apps = amo.APP_USAGE_FIREFOXES_ONLY
        else:
            available_apps = amo.APP_USAGE
        self.can_delete = not static_theme  # No tinkering with apps please.

        # Only display the apps we care about, if somehow obsolete apps were
        # recorded before.
        self.queryset = self.queryset.filter(
            application__in=[a.id for a in available_apps])
        initial_apps = self.queryset.values_list('application', flat=True)

        self.initial = ([{'application': appver.application,
                          'min': appver.min.pk,
                          'max': appver.max.pk} for appver in self.queryset] +
                        [{'application': app.id} for app in available_apps
                         if app.id not in initial_apps])
        self.extra = max(len(available_apps) - len(self.forms), 0)

        # After these changes, the forms need to be rebuilt. `forms`
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
                ugettext('Need at least one compatible application.'))


CompatFormSet = modelformset_factory(
    ApplicationsVersions, formset=BaseCompatFormSet,
    form=CompatForm, can_delete=True, extra=0)


class AddonUploadForm(WithSourceMixin, forms.Form):
    upload = forms.ModelChoiceField(
        widget=forms.HiddenInput,
        queryset=FileUpload.objects,
        to_field_name='uuid',
        error_messages={
            'invalid_choice': _(u'There was an error with your '
                                u'upload. Please try again.')
        }
    )
    admin_override_validation = forms.BooleanField(
        required=False, label=_(u'Override failed validation'))
    source = forms.FileField(required=False)
    is_manual_review = forms.BooleanField(
        initial=False, required=False,
        label=_(u'Submit my add-on for manual review.'))

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonUploadForm, self).__init__(*args, **kw)

    def _clean_upload(self):
        if not (self.cleaned_data['upload'].valid or
                self.cleaned_data['upload'].validation_timeout or
                self.cleaned_data['admin_override_validation'] and
                acl.action_allowed(self.request,
                                   amo.permissions.REVIEWS_ADMIN)):
            raise forms.ValidationError(
                ugettext(u'There was an error with your upload. '
                         u'Please try again.'))


class NewUploadForm(AddonUploadForm):
    supported_platforms = forms.TypedMultipleChoiceField(
        choices=amo.SUPPORTED_PLATFORMS_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'platform'}),
        initial=[amo.PLATFORM_ALL.id],
        coerce=int,
        error_messages={'required': 'Need at least one platform.'}
    )

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon', None)
        self.version = kw.pop('version', None)
        super(NewUploadForm, self).__init__(*args, **kw)

        # If we have a version reset platform choices to just those compatible.
        if self.version:
            platforms = self.fields['supported_platforms']
            compat_platforms = self.version.compatible_platforms().values()
            platforms.choices = sorted(
                (p.id, p.name) for p in compat_platforms)
            # Don't allow platforms we already have.
            to_exclude = set(File.objects.filter(version=self.version)
                                         .values_list('platform', flat=True))
            # Don't allow platform=ALL if we already have platform files.
            if to_exclude:
                to_exclude.add(amo.PLATFORM_ALL.id)
                platforms.choices = [p for p in platforms.choices
                                     if p[0] not in to_exclude]
            # Don't show the source field for new File uploads
            del self.fields['source']

    def clean(self):
        if self.version and not self.version.is_allowed_upload():
            raise forms.ValidationError(
                ugettext('You cannot upload any more files for this version.'))

        if not self.errors:
            self._clean_upload()
            parsed_data = parse_addon(
                self.cleaned_data['upload'], self.addon,
                user=self.request.user)

            if self.version:
                if parsed_data['version'] != self.version.version:
                    raise forms.ValidationError(
                        ugettext('Version doesn\'t match'))
            elif self.addon:
                # Make sure we don't already have this version.
                existing_versions = Version.unfiltered.filter(
                    addon=self.addon, version=parsed_data['version'])
                if existing_versions.exists():
                    version = existing_versions[0]
                    if version.deleted:
                        msg = ugettext(
                            u'Version {version} was uploaded before and '
                            u'deleted.')
                    elif version.unreviewed_files:
                        next_url = reverse('devhub.submit.version.details',
                                           args=[self.addon.slug, version.pk])
                        msg = jinja2.Markup('%s <a href="%s">%s</a>' % (
                            ugettext(u'Version {version} already exists.'),
                            next_url,
                            ugettext(u'Continue with existing upload instead?')
                        ))
                    else:
                        msg = ugettext(u'Version {version} already exists.')
                    raise forms.ValidationError(
                        msg.format(version=parsed_data['version']))
            self.cleaned_data['parsed_data'] = parsed_data
        return self.cleaned_data


class FileForm(forms.ModelForm):
    platform = File._meta.get_field('platform').formfield()

    class Meta:
        model = File
        fields = ('platform',)

    def __init__(self, *args, **kw):
        super(FileForm, self).__init__(*args, **kw)
        addon_type = kw['instance'].version.addon.type
        if addon_type in [amo.ADDON_SEARCH, amo.ADDON_STATICTHEME]:
            del self.fields['platform']
        else:
            compat = kw['instance'].version.compatible_platforms()
            pid = int(kw['instance'].platform)
            plats = [(p.id, p.name) for p in compat.values()]
            if pid not in compat:
                plats.append([pid, amo.PLATFORMS[pid].name])
            self.fields['platform'].choices = plats


class BaseFileFormSet(BaseModelFormSet):

    def clean(self):
        if any(self.errors):
            return
        files = [f.cleaned_data for f in self.forms]

        if self.forms and 'platform' in self.forms[0].fields:
            platforms = [f['platform'] for f in files]

            if amo.PLATFORM_ALL.id in platforms and len(files) > 1:
                raise forms.ValidationError(
                    ugettext('The platform All cannot be combined '
                             'with specific platforms.'))

            if sorted(platforms) != sorted(set(platforms)):
                raise forms.ValidationError(
                    ugettext('A platform can only be chosen once.'))


FileFormSet = modelformset_factory(File, formset=BaseFileFormSet,
                                   form=FileForm, can_delete=False, extra=0)


class DescribeForm(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}),
                         max_length=250)
    is_experimental = forms.BooleanField(required=False)
    requires_payment = forms.BooleanField(required=False)
    support_url = TransField.adapt(HttpHttpsOnlyURLField)(required=False)
    support_email = TransField.adapt(forms.EmailField)(required=False)
    has_priv = forms.BooleanField(
        required=False, label=_(u'This add-on has a Privacy Policy'),
        label_suffix='')
    privacy_policy = TransField(
        widget=TransTextarea(), required=False,
        label=_(u'Please specify your add-on\'s Privacy Policy:'))

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'is_experimental', 'support_url',
                  'support_email', 'privacy_policy', 'requires_payment')

    def __init__(self, *args, **kw):
        kw['initial'] = {
            'has_priv': self._has_field('privacy_policy', kw['instance'])}
        super(DescribeForm, self).__init__(*args, **kw)

    def _has_field(self, name, instance=None):
        # If there's a policy in any language, this addon has a policy.
        n = getattr(instance or self.instance, u'%s_id' % name)
        return any(map(bool, Translation.objects.filter(id=n)))

    def save(self, commit=True):
        obj = super(DescribeForm, self).save(commit)
        if not self.cleaned_data['has_priv']:
            delete_translation(self.instance, 'privacy_policy')

        return obj


class PreviewForm(forms.ModelForm):
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
                upload_path = os.path.join(
                    settings.TMP_PATH, 'preview', upload_hash)
                tasks.resize_preview.delay(
                    upload_path, self.instance.pk,
                    set_modified_on=self.instance.serializable_reference())

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


class CheckCompatibilityForm(forms.Form):
    application = forms.ChoiceField(
        label=_(u'Application'),
        choices=[(a.id, a.pretty) for a in amo.APP_USAGE])
    app_version = forms.ChoiceField(
        label=_(u'Version'),
        choices=[('', _(u'Select an application first'))])

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
    qs = (Addon.objects.public().exclude(id=addon_parent.id).
          exclude(type__in=[amo.ADDON_PERSONA]))

    class _Form(forms.ModelForm):
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
                raise forms.ValidationError(
                    ugettext('There cannot be more than 3 required add-ons.'))

    FormSet = modelformset_factory(AddonDependency, formset=_FormSet,
                                   form=_Form, extra=0, can_delete=True)
    return FormSet(*args, **kw)


class DistributionChoiceForm(forms.Form):
    LISTED_LABEL = _(
        u'On this site. <span class="helptext">'
        u'Your submission will be listed on this site and the Firefox '
        u'Add-ons Manager for millions of users, after it passes code '
        u'review. Automatic updates are handled by this site. This '
        u'add-on will also be considered for Mozilla promotions and '
        u'contests. Self-distribution of the reviewed files is also '
        u'possible.</span>')
    UNLISTED_LABEL = _(
        u'On your own. <span class="helptext">'
        u'Your submission will be immediately signed for '
        u'self-distribution. Updates should be handled by you via an '
        u'updateURL or external application updates.</span>')

    channel = forms.ChoiceField(
        choices=(
            ('listed', mark_safe_lazy(LISTED_LABEL)),
            ('unlisted', mark_safe_lazy(UNLISTED_LABEL))),
        initial='listed',
        widget=forms.RadioSelect(attrs={'class': 'channel'}))


class AgreementForm(forms.Form):
    distribution_agreement = forms.BooleanField()
    review_policy = forms.BooleanField()


class SingleCategoryForm(forms.Form):
    category = forms.ChoiceField(widget=forms.RadioSelect)

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request', None)
        if len(self.addon.all_categories) > 0:
            kw['initial'] = {'category': self.addon.all_categories[0].id}
        super(SingleCategoryForm, self).__init__(*args, **kw)

        # Hack because we know this is only used for Static Themes that only
        # support Firefox.  Hoping to unify per-app categories in the meantime.
        app = amo.FIREFOX
        sorted_cats = sorted(CATEGORIES[app.id][self.addon.type].items(),
                             key=lambda slug_cat: slug_cat[0])
        self.fields['category'].choices = [
            (c.id, c.name) for _, c in sorted_cats]

        # If this add-on is featured for this application, category changes are
        # forbidden.
        if not acl.action_allowed(self.request, amo.permissions.ADDONS_EDIT):
            self.disabled = self.addon.is_featured(app)

    def save(self):
        category = self.cleaned_data['category']
        # Clear any old categor[y|ies]
        AddonCategory.objects.filter(addon=self.addon).delete()
        # Add new category
        AddonCategory(addon=self.addon, category_id=category).save()
        # Remove old, outdated categories cache on the model.
        del self.addon.all_categories

    def clean_category(self):
        if getattr(self, 'disabled', False) and self.cleaned_data['category']:
            raise forms.ValidationError(ugettext(
                'Categories cannot be changed while your add-on is featured.'))

        return self.cleaned_data['category']
