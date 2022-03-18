import os
import tarfile
import zipfile

from urllib.parse import urlparse, urlsplit

from django import forms
from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db.models import Q
from django.forms.formsets import BaseFormSet, formset_factory
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.forms.widgets import RadioSelect
from django.urls import reverse
from django.utils.functional import keep_lazy_text
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _, ngettext

import waffle
from django_statsd.clients import statsd
from rest_framework.exceptions import Throttled

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons import tasks as addons_tasks
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonCategory,
    AddonUser,
    AddonUserPendingConfirmation,
    DeniedSlug,
    Preview,
)
from olympia.addons.utils import RestrictionChecker, verify_mozilla_trademark
from olympia.amo.fields import HttpHttpsOnlyURLField, ReCaptchaField
from olympia.amo.forms import AMOModelForm
from olympia.amo.messages import DoubleSafe
from olympia.amo.utils import remove_icons, slug_validator
from olympia.amo.validators import OneOrMoreLetterOrNumberCharacterValidator
from olympia.applications.models import AppVersion
from olympia.blocklist.models import Block
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID, CATEGORIES_NO_APP
from olympia.devhub.utils import fetch_existing_translations_from_addon
from olympia.devhub.widgets import CategoriesSelectMultiple, IconTypeSelect
from olympia.files.models import FileUpload
from olympia.files.utils import SafeZip, archive_member_validator, parse_addon
from olympia.tags.models import Tag
from olympia.translations import LOCALES
from olympia.translations.fields import LocaleErrorMessage, TransField, TransTextarea
from olympia.translations.forms import TranslationFormMixin
from olympia.translations.models import Translation, delete_translation
from olympia.translations.widgets import TranslationTextarea, TranslationTextInput
from olympia.users.models import (
    EmailUserRestriction,
    RESTRICTION_TYPES,
    UserEmailField,
    UserProfile,
)
from olympia.versions.models import (
    VALID_SOURCE_EXTENSIONS,
    ApplicationsVersions,
    DeniedInstallOrigin,
    License,
    Version,
)

from . import tasks


format_html_lazy = keep_lazy_text(format_html)


def clean_addon_slug(slug, instance):
    slug_validator(slug)

    if slug != instance.slug:
        if Addon.objects.filter(slug=slug).exists():
            raise forms.ValidationError(
                gettext('This slug is already in use. Please choose another.')
            )
        if DeniedSlug.blocked(slug):
            msg = gettext('The slug cannot be "%(slug)s". Please choose another.')
            raise forms.ValidationError(msg % {'slug': slug})

    return slug


class AddonFormBase(TranslationFormMixin, forms.ModelForm):
    fields_to_trigger_content_review = ('name', 'summary')

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        self.version = kw.pop('version', None)
        super().__init__(*args, **kw)
        for field in ('name', 'summary'):
            if field in self.fields:
                self.fields[field].validators.append(
                    OneOrMoreLetterOrNumberCharacterValidator()
                )

    class Meta:
        models = Addon
        fields = ('name', 'summary')

    def clean_slug(self):
        return clean_addon_slug(self.cleaned_data['slug'], self.instance)

    def clean_name(self):
        user = getattr(self.request, 'user', None)

        name = verify_mozilla_trademark(self.cleaned_data['name'], user, form=self)

        return name

    def save(self, *args, **kwargs):
        metadata_content_review = (
            waffle.switch_is_active('metadata-content-review')
            and self.instance
            and self.instance.has_listed_versions()
        )
        existing_data = (
            fetch_existing_translations_from_addon(
                self.instance, self.fields_to_trigger_content_review
            )
            if metadata_content_review
            else {}
        )
        obj = super().save(*args, **kwargs)
        if not metadata_content_review:
            return obj
        new_data = fetch_existing_translations_from_addon(
            obj, self.fields_to_trigger_content_review
        )
        if existing_data != new_data:
            # flag for content review
            statsd.incr('devhub.metadata_content_review_triggered')
            AddonApprovalsCounter.reset_content_for_addon(addon=obj)
        return obj


class CategoryForm(forms.Form):
    application = forms.TypedChoiceField(
        choices=amo.APPS_CHOICES, coerce=int, widget=forms.HiddenInput, required=True
    )
    categories = forms.MultipleChoiceField(choices=(), widget=CategoriesSelectMultiple)

    def save(self, addon):
        application = self.cleaned_data.get('application')
        categories_new = [int(c) for c in self.cleaned_data['categories']]
        categories_old = [
            c.id for c in addon.app_categories.get(amo.APP_IDS[application].short, [])
        ]

        # Add new categories.
        for c_id in set(categories_new) - set(categories_old):
            AddonCategory(addon=addon, category_id=c_id).save()

        # Remove old categories.
        for c_id in set(categories_old) - set(categories_new):
            AddonCategory.objects.filter(addon=addon, category_id=c_id).delete()

        # Remove old, outdated categories cache on the model.
        del addon.all_categories

        # Make sure the add-on is properly re-indexed
        addons_tasks.index_addons.delay([addon.id])

    def clean_categories(self):
        categories = self.cleaned_data['categories']
        total = len(categories)
        max_cat = amo.MAX_CATEGORIES

        if total > max_cat:
            # L10n: {0} is the number of categories.
            raise forms.ValidationError(
                ngettext(
                    'You can have only {0} category.',
                    'You can have only {0} categories.',
                    max_cat,
                ).format(max_cat)
            )

        has_misc = list(filter(lambda x: CATEGORIES_BY_ID.get(int(x)).misc, categories))
        if has_misc and total > 1:
            raise forms.ValidationError(
                gettext(
                    'The miscellaneous category cannot be combined with '
                    'additional categories.'
                )
            )

        return categories


class BaseCategoryFormSet(BaseFormSet):
    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request', None)
        super().__init__(*args, **kw)
        self.initial = []
        apps = sorted(self.addon.compatible_apps.keys(), key=lambda x: x.id)

        # Drop any apps that don't have appropriate categories.
        for app in list(apps):
            if app and not CATEGORIES.get(app.id, {}).get(self.addon.type):
                apps.remove(app)

        if not CATEGORIES_NO_APP.get(self.addon.type):
            apps = []

        for app in apps:
            cats = self.addon.app_categories.get(app.short, [])
            self.initial.append({'categories': [c.id for c in cats]})

        for app, form in zip(apps, self.forms):
            key = app.id if app else None
            form.request = self.request
            form.initial['application'] = key
            form.app = app
            cats = sorted(
                CATEGORIES.get(key, {}).get(self.addon.type, {}).values(),
                key=lambda x: x.name,
            )
            form.fields['categories'].choices = [(c.id, c.name) for c in cats]

    def save(self):
        for f in self.forms:
            f.save(self.addon)


CategoryFormSet = formset_factory(
    form=CategoryForm, formset=BaseCategoryFormSet, extra=0
)


ICON_TYPES = [('', 'default'), ('image/jpeg', 'jpeg'), ('image/png', 'png')]


class AddonFormMedia(AddonFormBase):
    icon_type = forms.CharField(
        widget=IconTypeSelect(choices=ICON_TYPES), required=False
    )
    icon_upload_hash = forms.CharField(required=False)

    class Meta:
        model = Addon
        fields = ('icon_upload_hash', 'icon_type')

    def save(self, addon, commit=True):
        if self.cleaned_data['icon_upload_hash']:
            upload_hash = self.cleaned_data['icon_upload_hash']
            upload_path = os.path.join(settings.TMP_PATH, 'icon', upload_hash)

            dirname = addon.get_icon_dir()
            destination = os.path.join(dirname, '%s' % addon.id)

            remove_icons(destination)
            addons_tasks.resize_icon.delay(
                upload_path,
                destination,
                amo.ADDON_ICON_SIZES,
                set_modified_on=addon.serializable_reference(),
            )

        return super().save(commit)


class AdditionalDetailsForm(AddonFormBase):
    default_locale = forms.TypedChoiceField(choices=LOCALES)
    homepage = TransField.adapt(HttpHttpsOnlyURLField)(required=False)
    tags = forms.MultipleChoiceField(
        choices=(), widget=forms.CheckboxSelectMultiple, required=False
    )
    contributions = HttpHttpsOnlyURLField(required=False, max_length=255)

    class Meta:
        model = Addon
        fields = ('default_locale', 'homepage', 'tags', 'contributions')

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)

        if tags_field := self.fields.get('tags'):
            self.all_tags = {t.tag_text: t for t in Tag.objects.all()}
            tags_field.choices = ((t, t) for t in self.all_tags)
            tags_field.initial = list(
                self.instance.tags.all().values_list('tag_text', flat=True)
            )

    def clean_contributions(self):
        if self.cleaned_data['contributions']:
            parsed_url = urlsplit(self.cleaned_data['contributions'])
            hostname = parsed_url.hostname
            path = parsed_url.path

            if not hostname.endswith(amo.VALID_CONTRIBUTION_DOMAINS):
                raise forms.ValidationError(
                    gettext('URL domain must be one of [%s], or a subdomain.')
                    % ', '.join(amo.VALID_CONTRIBUTION_DOMAINS)
                )
            elif hostname == 'github.com' and not path.startswith('/sponsors/'):
                # Issue 15497, validate path for GitHub Sponsors
                raise forms.ValidationError(
                    gettext('URL path for GitHub Sponsors must contain /sponsors/.')
                )

        return self.cleaned_data['contributions']

    def clean_tags(self):
        tags = self.cleaned_data['tags']
        if (over := len(tags) - amo.MAX_TAGS) > 0:
            msg = ngettext(
                'You have {0} too many tags.', 'You have {0} too many tags.', over
            ).format(over)
            raise forms.ValidationError(msg)
        return tags

    def clean(self):
        # Make sure we have the required translations in the new locale.
        required = 'name', 'summary', 'description'
        if not self.errors and 'default_locale' in self.changed_data:
            fields = {k: getattr(self.instance, k + '_id') for k in required}
            locale = self.cleaned_data['default_locale']
            ids = filter(None, fields.values())
            qs = Translation.objects.filter(
                locale=locale, id__in=ids, localized_string__isnull=False
            ).values_list('id', flat=True)
            missing = [k for k, v in fields.items() if v not in qs]
            if missing:
                raise forms.ValidationError(
                    gettext(
                        'Before changing your default locale you must have a '
                        'name, summary, and description in that locale. '
                        'You are missing %s.'
                    )
                    % ', '.join(map(repr, missing))
                )
        return super().clean()

    def save(self, addon, commit=False):
        if self.fields.get('tags'):
            tags_new = self.cleaned_data['tags']
            tags_old = self.fields['tags'].initial

            # Add new tags.
            for t in set(tags_new) - set(tags_old):
                self.all_tags[t].add_tag(addon)

            # Remove old tags.
            for t in set(tags_old) - set(tags_new):
                self.all_tags[t].remove_tag(addon)

        # We ignore `commit`, since we need it to be `False` so we can save
        # the ManyToMany fields on our own.
        addonform = super().save(commit=False)
        addonform.save()

        return addonform


class AdditionalDetailsFormUnlisted(AdditionalDetailsForm):
    # We want the same fields as the listed version. In particular,
    # default_locale is referenced in the template and needs to exist.
    pass


class AddonFormTechnical(AddonFormBase):
    developer_comments = TransField(widget=TransTextarea, required=False)

    class Meta:
        model = Addon
        fields = ('developer_comments',)


class AddonFormTechnicalUnlisted(AddonFormBase):
    class Meta:
        model = Addon
        fields = ()


class AuthorForm(forms.ModelForm):
    user = UserEmailField(required=True, queryset=UserProfile.objects.all())
    role = forms.TypedChoiceField(
        required=True,
        choices=amo.AUTHOR_CHOICES,
        initial=amo.AUTHOR_ROLE_OWNER,
        coerce=int,
    )

    class Meta:
        model = AddonUser
        exclude = ('addon',)

    def __init__(self, *args, **kwargs):
        # addon should be passed through form_kwargs={'addon': addon} when
        # initializing the formset.
        self.addon = kwargs.pop('addon')
        super().__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            # Clients are not allowed to change existing authors. If they want
            # to do that, they need to remove the existing author and add a new
            # one. This makes the confirmation system easier to manage.
            self.fields['user'].disabled = True

            # Set the email to be displayed in the form instead of the pk.
            self.initial['user'] = instance.user.email

    def clean(self):
        rval = super().clean()
        if self._meta.model == AddonUser and (
            self.instance is None or not self.instance.pk
        ):
            # This should never happen, the client is trying to add a user
            # directly to AddonUser through the formset, they should have
            # been added to AuthorWaitingConfirmation instead.
            raise forms.ValidationError(gettext('Users can not be added directly'))
        return rval


class AuthorWaitingConfirmationForm(AuthorForm):
    class Meta(AuthorForm.Meta):
        model = AddonUserPendingConfirmation

    def clean_user(self):
        user = self.cleaned_data.get('user')
        if user:
            if not EmailUserRestriction.allow_email(
                user.email, restriction_type=RESTRICTION_TYPES.SUBMISSION
            ):
                raise forms.ValidationError(EmailUserRestriction.error_message)

            if self.addon.authors.filter(pk=user.pk).exists():
                raise forms.ValidationError(
                    gettext('An author can only be present once.')
                )

            name_validators = user._meta.get_field('display_name').validators
            try:
                if user.display_name is None:
                    raise forms.ValidationError('')  # Caught below.
                for validator in name_validators:
                    validator(user.display_name)
            except forms.ValidationError:
                raise forms.ValidationError(
                    gettext(
                        'The account needs a display name before it can be added '
                        'as an author.'
                    )
                )
        return user


class BaseModelFormSet(BaseModelFormSet):
    """
    Override the parent's is_valid to prevent deleting all forms.
    """

    def is_valid(self):
        # clean() won't get called in is_valid() if all the rows are getting
        # deleted. We can't allow deleting everything.
        rv = super().is_valid()
        return rv and not any(self.errors) and not bool(self.non_form_errors())


class BaseAuthorFormSet(BaseModelFormSet):
    def clean(self):
        if any(self.errors):
            return
        # cleaned_data could be None if it's the empty extra form.
        data = list(
            filter(
                None,
                [
                    f.cleaned_data
                    for f in self.forms
                    if not f.cleaned_data.get('DELETE', False)
                ],
            )
        )
        if not any(d['role'] == amo.AUTHOR_ROLE_OWNER for d in data):
            raise forms.ValidationError(gettext('Must have at least one owner.'))
        if not any(d['listed'] for d in data):
            raise forms.ValidationError(gettext('At least one author must be listed.'))


class BaseAuthorWaitingConfirmationFormSet(BaseModelFormSet):
    def clean(self):
        if any(self.errors):
            return

        # cleaned_data could be None if it's the empty extra form.
        data = list(
            filter(
                None,
                [
                    f.cleaned_data
                    for f in self.forms
                    if not f.cleaned_data.get('DELETE', False)
                ],
            )
        )
        users = [d['user'].id for d in data]
        if len(users) != len(set(users)):
            raise forms.ValidationError(gettext('An author can only be present once.'))


AuthorFormSet = modelformset_factory(
    AddonUser, formset=BaseAuthorFormSet, form=AuthorForm, can_delete=True, extra=0
)

AuthorWaitingConfirmationFormSet = modelformset_factory(
    AddonUserPendingConfirmation,
    formset=BaseAuthorWaitingConfirmationFormSet,
    form=AuthorWaitingConfirmationForm,
    can_delete=True,
    extra=0,
)


class DeleteForm(forms.Form):
    slug = forms.CharField()
    reason = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.addon = kwargs.pop('addon')
        super().__init__(*args, **kwargs)

    def clean_slug(self):
        data = self.cleaned_data
        if not data['slug'] == self.addon.slug:
            raise forms.ValidationError(gettext('Slug incorrect.'))


class LicenseRadioSelect(forms.RadioSelect):
    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)

        # Make sure the `class` is only set on the radio fields and
        # not on the `ul`. This avoids style issues among other things.
        # See https://github.com/mozilla/addons-server/issues/8902
        # and https://github.com/mozilla/addons-server/issues/8920
        del context['widget']['attrs']['class']

        return context

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        context = super().create_option(
            name=name,
            value=value,
            label=label,
            selected=selected,
            index=index,
            subindex=subindex,
            attrs=attrs,
        )

        link = (
            '<a class="xx extra" href="%s" target="_blank" '
            'rel="noopener noreferrer">%s</a>'
        )
        license = self.choices[index][1]

        if hasattr(license, 'url') and license.url:
            details = link % (license.url, gettext('Details'))
            context['label'] = mark_safe(str(context['label']) + ' ' + details)
        if hasattr(license, 'icons'):
            context['attrs']['data-cc'] = license.icons
        context['attrs']['data-name'] = str(license)
        return context


class LicenseForm(AMOModelForm):
    # Hack to restore behavior from pre Django 1.10 times.
    # Django 1.10 enabled `required` rendering for required widgets. That
    # wasn't the case before, this should be fixed properly but simplifies
    # the actual Django 1.11 deployment for now.
    # See https://github.com/mozilla/addons-server/issues/8912 for proper fix.
    use_required_attribute = False

    builtin = forms.TypedChoiceField(
        choices=[], coerce=int, widget=LicenseRadioSelect(attrs={'class': 'license'})
    )
    name = forms.CharField(
        widget=TranslationTextInput(),
        label=_("What is your license's name?"),
        required=False,
        initial=_('Custom License'),
    )
    text = forms.CharField(
        widget=TranslationTextarea(),
        required=False,
        label=_('Provide the text of your license.'),
    )

    def __init__(self, *args, **kwargs):
        self.version = kwargs.pop('version', None)
        if self.version:
            kwargs['instance'], kwargs['initial'] = self.version.license, None
            # Clear out initial data if it's a builtin license.
            if getattr(kwargs['instance'], 'builtin', None):
                kwargs['initial'] = {'builtin': kwargs['instance'].builtin}
                kwargs['instance'] = None
            self.cc_licenses = kwargs.pop(
                'cc', self.version.addon.type == amo.ADDON_STATICTHEME
            )
        else:
            self.cc_licenses = kwargs.pop('cc', False)

        super().__init__(*args, **kwargs)
        licenses = License.objects.builtins(cc=self.cc_licenses).filter(on_form=True)
        cs = [(x.builtin, x) for x in licenses]
        if not self.cc_licenses:
            # creative commons licenses don't have an 'other' option.
            cs.append((License.OTHER, gettext('Other')))
        self.fields['builtin'].choices = cs
        if self.version and self.version.channel == amo.RELEASE_CHANNEL_UNLISTED:
            self.fields['builtin'].required = False

    class Meta:
        model = License
        fields = ('builtin', 'name', 'text')

    def clean_name(self):
        name = self.cleaned_data['name']
        return name.strip() or gettext('Custom License')

    def clean(self):
        data = self.cleaned_data
        if self.errors:
            return data
        elif data['builtin'] == License.OTHER and not data['text']:
            raise forms.ValidationError(
                gettext('License text is required when choosing Other.')
            )
        return data

    def get_context(self):
        """Returns a view context dict having keys license_form,
        and license_other_val.
        """
        return {
            'version': self.version,
            'license_form': self.version and self,
            'license_other_val': License.OTHER,
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
            license = super().save(*args, **kw)

        if self.version:
            if (changed and is_other) or license != self.version.license:
                self.version.update(license=license)
                if log:
                    ActivityLog.create(
                        amo.LOG.CHANGE_LICENSE, license, self.version.addon
                    )
        return license


class PolicyForm(TranslationFormMixin, AMOModelForm):
    """Form for editing the add-ons EULA and privacy policy."""

    has_eula = forms.BooleanField(
        required=False, label=_('This add-on has an End-User License Agreement')
    )
    eula = TransField(
        widget=TransTextarea(),
        required=False,
        label=_("Please specify your add-on's " 'End-User License Agreement:'),
    )
    has_priv = forms.BooleanField(
        required=False, label=_('This add-on has a Privacy Policy'), label_suffix=''
    )
    privacy_policy = TransField(
        widget=TransTextarea(),
        required=False,
        label=_("Please specify your add-on's Privacy Policy:"),
    )

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon', None)
        if not self.addon:
            raise ValueError('addon keyword arg cannot be None')
        kw['instance'] = self.addon
        kw['initial'] = dict(
            has_priv=self._has_field('privacy_policy'), has_eula=self._has_field('eula')
        )
        super().__init__(*args, **kw)

    def _has_field(self, name):
        # If there's a eula in any language, this addon has a eula.
        n = getattr(self.addon, '%s_id' % name)
        return any(map(bool, Translation.objects.filter(id=n)))

    class Meta:
        model = Addon
        fields = ('eula', 'privacy_policy')

    def save(self, commit=True):
        ob = super().save(commit)
        for k, field in (('has_eula', 'eula'), ('has_priv', 'privacy_policy')):
            if not self.cleaned_data[k]:
                delete_translation(self.instance, field)

        if 'privacy_policy' in self.changed_data:
            ActivityLog.create(amo.LOG.CHANGE_POLICY, self.addon, self.instance)

        return ob


class WithSourceMixin:
    def get_invalid_source_file_type_message(self):
        valid_extensions_string = '(%s)' % ', '.join(VALID_SOURCE_EXTENSIONS)
        return gettext(
            'Unsupported file type, please upload an archive '
            'file {extensions}.'.format(extensions=valid_extensions_string)
        )

    def clean_source(self):
        source = self.cleaned_data.get('source')
        if source:
            # Ensure the file type is one we support.
            if not source.name.endswith(VALID_SOURCE_EXTENSIONS):
                raise forms.ValidationError(self.get_invalid_source_file_type_message())
            # Check inside to see if the file extension matches the content.
            try:
                if source.name.endswith('.zip'):
                    zip_file = SafeZip(source)
                    # testzip() returns None if there are no broken CRCs.
                    if zip_file.zip_file.testzip() is not None:
                        raise zipfile.BadZipFile()
                elif source.name.endswith(('.tar.gz', '.tar.bz2', '.tgz')):
                    # For tar files we need to do a little more work.
                    mode = 'r:bz2' if source.name.endswith('bz2') else 'r:gz'
                    with tarfile.open(mode=mode, fileobj=source) as archive:
                        archive_members = archive.getmembers()
                        for member in archive_members:
                            archive_member_validator(archive, member)
                else:
                    raise forms.ValidationError(
                        self.get_invalid_source_file_type_message()
                    )
            except (zipfile.BadZipFile, tarfile.ReadError, OSError, EOFError):
                raise forms.ValidationError(gettext('Invalid or broken archive.'))
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
        context = super().get_context(name, value, attrs)
        if value and hasattr(value, 'instance'):
            context['download_url'] = reverse(
                'downloads.source', args=(value.instance.pk,)
            )
        return context


class VersionForm(WithSourceMixin, forms.ModelForm):
    release_notes = TransField(widget=TransTextarea(), required=False)
    approval_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4}), required=False
    )
    source = forms.FileField(required=False, widget=SourceFileInput)

    class Meta:
        model = Version
        fields = (
            'release_notes',
            'approval_notes',
            'source',
        )


class AppVersionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.version


class CompatForm(forms.ModelForm):
    application = forms.TypedChoiceField(
        choices=amo.APPS_CHOICES, coerce=int, widget=forms.HiddenInput
    )
    min = AppVersionChoiceField(AppVersion.objects.none())
    max = AppVersionChoiceField(AppVersion.objects.none())

    class Meta:
        model = ApplicationsVersions
        fields = ('application', 'min', 'max')

    def __init__(self, *args, **kwargs):
        # 'version' should always be passed as a kwarg to this form. If it's
        # absent, it probably means form_kwargs={'version': version} is missing
        # from the instantiation of the formset.
        super().__init__(*args, **kwargs)
        if self.initial:
            app = self.initial['application']
        else:
            app = self.data[self.add_prefix('application')]
        self.app = amo.APPS_ALL[int(app)]
        qs = AppVersion.objects.filter(application=app).order_by('version_int')

        self.fields['min'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max'].queryset = qs.all()

    def clean(self):
        min_ = self.cleaned_data.get('min')
        max_ = self.cleaned_data.get('max')
        if not (min_ and max_ and min_.version_int <= max_.version_int):
            raise forms.ValidationError(gettext('Invalid version range.'))
        return self.cleaned_data


class BaseCompatFormSet(BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We always want a form for each app, so force extras for apps
        # the add-on does not already have.
        version = self.form_kwargs.pop('version')
        static_theme = version and version.addon.type == amo.ADDON_STATICTHEME
        available_apps = amo.APP_USAGE
        self.can_delete = not static_theme  # No tinkering with apps please.

        # Only display the apps we care about, if somehow obsolete apps were
        # recorded before.
        self.queryset = self.queryset.filter(
            application__in=[a.id for a in available_apps]
        )
        initial_apps = self.queryset.values_list('application', flat=True)

        self.initial = [
            {
                'application': appver.application,
                'min': appver.min.pk,
                'max': appver.max.pk,
            }
            for appver in self.queryset
        ] + [
            {'application': app.id}
            for app in available_apps
            if app.id not in initial_apps
        ]
        self.extra = (
            max(len(available_apps) - len(self.forms), 0) if not static_theme else 0
        )

        # After these changes, the forms need to be rebuilt. `forms`
        # is a cached property, so we delete the existing cache and
        # ask for a new one to be built.
        # del self.forms
        if hasattr(self, 'forms'):
            del self.forms
        self.forms

    def clean(self):
        if any(self.errors):
            return

        apps = list(
            filter(
                None,
                [
                    f.cleaned_data
                    for f in self.forms
                    if not f.cleaned_data.get('DELETE', False)
                ],
            )
        )

        if not apps:
            # At this point, we're raising a global error and re-displaying the
            # applications that were present before. We don't want to keep the
            # hidden delete fields in the data attribute, cause that's used to
            # populate initial data for all forms, and would therefore make
            # those delete fields active again.
            self.data = {
                k: v for k, v in self.data.items() if not k.endswith('-DELETE')
            }
            for form in self.forms:
                form.data = self.data
            raise forms.ValidationError(
                gettext('Need at least one compatible application.')
            )


CompatFormSet = modelformset_factory(
    ApplicationsVersions,
    formset=BaseCompatFormSet,
    form=CompatForm,
    can_delete=True,
    extra=0,
)


class CompatAppSelectWidget(forms.CheckboxSelectMultiple):
    option_template_name = 'devhub/forms/widgets/compat_app_input_option.html'

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        data = super().create_option(
            name=name,
            value=value,
            label=label,
            selected=selected,
            index=index,
            subindex=subindex,
            attrs=attrs,
        )

        # Inject the short application name for easier styling
        data['compat_app_short'] = amo.APPS_ALL[int(data['value'])].short

        return data


class CheckThrottlesMixin:
    def check_throttles(self, request):
        """
        Check if request should be throttled by calling the signing API
        throttling method.

        Raises ValidationError if the request is throttled.
        """
        from olympia.signing.views import VersionView  # circular import

        view = VersionView()
        try:
            view.check_throttles(request)
        except Throttled:
            raise forms.ValidationError(
                _(
                    'You have submitted too many uploads recently. '
                    'Please try again after some time.'
                )
            )


class NewUploadForm(CheckThrottlesMixin, forms.Form):
    upload = forms.ModelChoiceField(
        widget=forms.HiddenInput,
        queryset=FileUpload.objects,
        to_field_name='uuid',
        error_messages={
            'invalid_choice': _(
                'There was an error with your upload. Please try again.'
            )
        },
    )
    admin_override_validation = forms.BooleanField(
        required=False, label=_('Override failed validation')
    )
    compatible_apps = forms.TypedMultipleChoiceField(
        choices=amo.APPS_CHOICES,
        # Pre-select only Desktop Firefox, most of the times developers
        # don't develop their WebExtensions for Android.
        # See this GitHub comment: https://bit.ly/2QaMicU
        initial=[amo.FIREFOX.id],
        coerce=int,
        widget=CompatAppSelectWidget(),
        error_messages={'required': _('Need to select at least one application.')},
    )

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        self.addon = kw.pop('addon', None)
        super().__init__(*args, **kw)

        # Preselect compatible apps based on the current version
        if self.addon and self.addon.current_version:
            # Fetch list of applications freshly from the database to not
            # rely on potentially outdated data since `addon.compatible_apps`
            # is a cached property
            compat_apps = list(
                self.addon.current_version.apps.values_list('application', flat=True)
            )
            self.fields['compatible_apps'].initial = compat_apps

    def _clean_upload(self):
        own_upload = self.cleaned_data['upload'].user == self.request.user

        if (
            not own_upload
            or not self.cleaned_data['upload'].valid
            or self.cleaned_data['upload'].validation_timeout
        ) and not (
            self.cleaned_data['admin_override_validation']
            and acl.action_allowed(self.request, amo.permissions.REVIEWS_ADMIN)
        ):
            raise forms.ValidationError(
                gettext('There was an error with your upload. Please try again.')
            )

    def check_blocklist(self, guid, version_string):
        # check the guid/version isn't in the addon blocklist
        block = Block.objects.filter(guid=guid).first()
        if block and block.is_version_blocked(version_string):
            msg = escape(
                gettext(
                    'Version {version} matches {block_link} for this add-on. '
                    'You can contact {amo_admins} for additional information.'
                )
            )
            formatted_msg = DoubleSafe(
                msg.format(
                    version=version_string,
                    block_link=format_html(
                        '<a href="{}">{}</a>',
                        reverse('blocklist.block', args=[guid]),
                        gettext('a blocklist entry'),
                    ),
                    amo_admins=(
                        '<a href="mailto:amo-admins@mozilla.com">AMO Admins</a>'
                    ),
                )
            )
            raise forms.ValidationError(formatted_msg)

    def check_for_existing_versions(self, version_string):
        if self.addon:
            # Make sure we don't already have this version.
            existing_versions = Version.unfiltered.filter(
                addon=self.addon, version=version_string
            )
            if existing_versions.exists():
                version = existing_versions[0]
                if version.deleted:
                    msg = gettext('Version {version} was uploaded before and deleted.')
                elif version.file.status == amo.STATUS_AWAITING_REVIEW:
                    next_url = reverse(
                        'devhub.submit.version.details',
                        args=[self.addon.slug, version.pk],
                    )
                    msg = DoubleSafe(
                        '%s <a href="%s">%s</a>'
                        % (
                            gettext('Version {version} already exists.'),
                            next_url,
                            gettext('Continue with existing upload instead?'),
                        )
                    )
                else:
                    msg = gettext('Version {version} already exists.')
                raise forms.ValidationError(msg.format(version=version_string))

    def clean(self):
        self.check_throttles(self.request)

        if not self.errors:
            self._clean_upload()
            parsed_data = parse_addon(
                self.cleaned_data['upload'], self.addon, user=self.request.user
            )

            self.check_blocklist(
                self.addon.guid if self.addon else parsed_data.get('guid'),
                parsed_data.get('version'),
            )
            self.check_for_existing_versions(parsed_data.get('version'))

            self.cleaned_data['parsed_data'] = parsed_data
        return self.cleaned_data


class SourceForm(WithSourceMixin, forms.ModelForm):
    source = forms.FileField(required=False, widget=SourceFileInput)
    has_source = forms.ChoiceField(
        choices=(('yes', _('Yes')), ('no', _('No'))), required=True, widget=RadioSelect
    )

    class Meta:
        model = Version
        fields = ('source',)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super().__init__(*args, **kwargs)

    def clean_source(self):
        source = self.cleaned_data.get('source')
        has_source = self.data.get('has_source')  # Not cleaned yet.
        if has_source == 'yes' and not source:
            raise forms.ValidationError(gettext('You have not uploaded a source file.'))
        elif has_source == 'no' and source:
            raise forms.ValidationError(
                gettext('Source file uploaded but you indicated no source was needed.')
            )
        # At this point we know we can proceed with the actual archive
        # validation.
        return super().clean_source()


class DescribeForm(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}), max_length=250)
    description = TransField(widget=TransTextarea(attrs={'rows': 6}), min_length=10)
    is_experimental = forms.BooleanField(required=False)
    requires_payment = forms.BooleanField(required=False)
    support_url = TransField.adapt(HttpHttpsOnlyURLField)(required=False)
    support_email = TransField.adapt(forms.EmailField)(required=False)

    class Meta:
        model = Addon
        fields = (
            'name',
            'slug',
            'summary',
            'description',
            'is_experimental',
            'support_url',
            'support_email',
            'requires_payment',
        )

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        content_waffle = waffle.switch_is_active('content-optimization')
        if not content_waffle or self.instance.type != amo.ADDON_EXTENSION:
            description = self.fields['description']
            description.min_length = None
            description.widget.attrs.pop('minlength', None)
            description.validators = [
                validator
                for validator in description.validators
                if not isinstance(validator, MinLengthValidator)
            ]
            description.required = False


class CombinedNameSummaryCleanMixin:
    MAX_LENGTH = 70

    def __init__(self, *args, **kw):
        self.should_auto_crop = kw.pop('should_auto_crop', False)
        super().__init__(*args, **kw)
        # We need the values for the template but not the MaxLengthValidators
        self.fields['name'].max_length = (
            self.MAX_LENGTH - self.fields['summary'].min_length
        )
        self.fields['summary'].max_length = (
            self.MAX_LENGTH - self.fields['name'].min_length
        )

    def clean(self):
        message = _(
            'Ensure name and summary combined are at most '
            '{limit_value} characters (they have {show_value}).'
        )
        super().clean()
        name_summary_locales = set(
            list(self.cleaned_data.get('name', {}).keys())
            + list(self.cleaned_data.get('summary', {}).keys())
        )
        default_locale = self.instance.default_locale.lower()
        name_values = self.cleaned_data.get('name') or {}
        name_default = name_values.get(default_locale) or ''
        summary_values = self.cleaned_data.get('summary') or {}
        summary_default = summary_values.get(default_locale) or ''
        for locale in name_summary_locales:
            val_len = len(
                name_values.get(locale, name_default)
                + summary_values.get(locale, summary_default)
            )
            if val_len > self.MAX_LENGTH:
                if locale == default_locale:
                    # only error in default locale.
                    formatted_message = message.format(
                        limit_value=self.MAX_LENGTH, show_value=val_len
                    )
                    self.add_error(
                        'name',
                        LocaleErrorMessage(message=formatted_message, locale=locale),
                    )
                elif self.should_auto_crop:
                    # otherwise we need to shorten the summary (and or name?)
                    if locale in name_values:
                        # if only default summary need to shorten name instead.
                        max_name_length = (
                            self.fields['name'].max_length
                            if locale in summary_values
                            else self.MAX_LENGTH - len(summary_default)
                        )
                        name = name_values[locale][:max_name_length]
                        name_length = len(name)
                        self.cleaned_data.setdefault('name', {})[locale] = name
                    else:
                        name_length = len(name_default)
                    if locale in summary_values:
                        max_summary_length = self.MAX_LENGTH - name_length
                        self.cleaned_data.setdefault('summary', {})[
                            locale
                        ] = summary_values[locale][:max_summary_length]
        return self.cleaned_data


class DescribeFormContentOptimization(CombinedNameSummaryCleanMixin, DescribeForm):
    name = TransField(min_length=2)
    summary = TransField(min_length=2)


class DescribeFormUnlisted(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}), max_length=250)
    description = TransField(widget=TransTextarea(attrs={'rows': 4}), required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'description')


class DescribeFormUnlistedContentOptimization(
    CombinedNameSummaryCleanMixin, DescribeFormUnlisted
):
    name = TransField(max_length=68, min_length=2)
    summary = TransField(max_length=68, min_length=2)


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

            super().save(commit=commit)
            if self.cleaned_data['upload_hash']:
                upload_hash = self.cleaned_data['upload_hash']
                upload_path = os.path.join(settings.TMP_PATH, 'preview', upload_hash)
                tasks.resize_preview.delay(
                    upload_path,
                    self.instance.pk,
                    set_modified_on=self.instance.serializable_reference(),
                )

    class Meta:
        model = Preview
        fields = ('caption', 'file_upload', 'upload_hash', 'id', 'position')


class BasePreviewFormSet(BaseModelFormSet):
    def clean(self):
        if any(self.errors):
            return


PreviewFormSet = modelformset_factory(
    Preview, formset=BasePreviewFormSet, form=PreviewForm, can_delete=True, extra=1
)


class DistributionChoiceForm(forms.Form):
    # Gotta keep the format_html call lazy, otherwise these would be evaluated
    # to a string right away and never translated.
    LISTED_LABEL = format_html_lazy(
        _(
            'On this site. <span class="helptext">'
            'Your submission is publicly listed on {site_domain}.</span>'
        ),
        site_domain=settings.DOMAIN,
    )
    UNLISTED_LABEL = format_html_lazy(
        _(
            'On your own. <span class="helptext">'
            'After your submission is signed by Mozilla, you can download the .xpi '
            'file from the Developer Hub and distribute it to your audience. Please '
            'make sure the add-on manifest’s <a {a_attrs}>update_url</a> is provided, '
            'as this is the URL where Firefox finds updates for automatic deployment '
            'to your users.</span>'
        ),
        a_attrs=mark_safe(
            'target="_blank" rel="noopener noreferrer"'
            f'href="{settings.EXTENSION_WORKSHOP_URL}'
            '/documentation/manage/updating-your-extension/'
            '?utm_source=addons.mozilla.org&utm_medium=referral&utm_content=submission"'
        ),
    )

    channel = forms.ChoiceField(
        choices=[],
        initial='listed',
        widget=forms.RadioSelect(attrs={'class': 'channel'}),
    )

    def __init__(self, *args, **kwargs):
        self.addon = kwargs.pop('addon', None)
        super().__init__(*args, **kwargs)
        choices = [
            ('listed', mark_safe(self.LISTED_LABEL)),
            ('unlisted', mark_safe(self.UNLISTED_LABEL)),
        ]
        if self.addon and self.addon.disabled_by_user:
            # If the add-on is disabled, 'listed' is not a valid choice,
            # "invisible" add-ons can not upload new listed versions.
            choices.pop(0)

        self.fields['channel'].choices = choices


class AgreementForm(forms.Form):
    distribution_agreement = forms.BooleanField()
    review_policy = forms.BooleanField()
    display_name = forms.CharField(label=_('Display Name'))
    recaptcha = ReCaptchaField(label='')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)

        super().__init__(*args, **kwargs)

        if not waffle.switch_is_active('developer-agreement-captcha'):
            del self.fields['recaptcha']

        if self.request.user.is_authenticated and self.request.user.display_name:
            # Don't bother asking for a display name if there is one already.
            del self.fields['display_name']
        else:
            # If there isn't one... we want to make sure to use the same
            # validators as the model.
            self.fields['display_name'].validators += UserProfile._meta.get_field(
                'display_name'
            ).validators

    def clean(self):
        # Check if user ip or email is not supposed to be allowed to submit.
        checker = RestrictionChecker(request=self.request)
        if not checker.is_submission_allowed(check_dev_agreement=False):
            raise forms.ValidationError(checker.get_error_message())
        return self.cleaned_data


class SingleCategoryForm(forms.Form):
    category = forms.ChoiceField(widget=forms.RadioSelect)

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request', None)
        if len(self.addon.all_categories) > 0:
            kw['initial'] = {'category': self.addon.all_categories[0].slug}
        super().__init__(*args, **kw)

        sorted_cats = sorted(
            CATEGORIES_NO_APP[self.addon.type].items(), key=lambda slug_cat: slug_cat[0]
        )
        self.fields['category'].choices = [(slug, c.name) for slug, c in sorted_cats]

    def save(self):
        category_slug = self.cleaned_data['category']
        # Clear any old categor[y|ies]
        AddonCategory.objects.filter(addon=self.addon).delete()
        # Add new categor[y|ies]
        for app in CATEGORIES.keys():
            category = CATEGORIES[app].get(self.addon.type, {}).get(category_slug, None)
            if category:
                AddonCategory(addon=self.addon, category_id=category.id).save()
        # Remove old, outdated categories cache on the model.
        del self.addon.all_categories


class SitePermissionGeneratorForm(CheckThrottlesMixin, forms.Form):
    origin = forms.URLField(
        label=_('Origin'),
        widget=forms.TextInput(attrs={'placeholder': 'https://example.com'}),
    )
    site_permissions = forms.MultipleChoiceField(
        label=_('Permissions'), choices=(('midi-sysex', 'WebMIDI'),)
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        self.check_throttles(self.request)
        origin = self.cleaned_data.get('origin')
        site_permissions = self.cleaned_data.get('site_permissions')
        already_exists = (
            self.request.user.addons.all()
            .filter(
                type=amo.ADDON_SITE_PERMISSION,
                versions__installorigin__origin=origin,
                versions__file___site_permissions__permissions=site_permissions,
            )
            .exists()
        )
        if already_exists:
            raise forms.ValidationError(
                _(
                    'You have generated a site permission add-on for the same origin '
                    'and permissions.'
                )
            )

    def clean_origin(self):
        actual_value = str(self.data.get('origin'))
        value = self.cleaned_data.get('origin')
        # Note that URLField should already ensure it's an URL.
        error_message = _(
            'Origin should include only a scheme (protocol), a hostname (domain) and '
            'an optional port'
        )
        try:
            parsed = urlparse(value)
        except ValueError:
            raise forms.ValidationError(error_message)
        if (
            not parsed.scheme
            or parsed.scheme not in ('https', 'http')
            or not parsed.netloc
            # Django's URLField adds a scheme if there wasn't one, translating
            # "foo" into "http://foo". We want to make sure the scheme was
            # explicitly present in the submitted value.
            or not actual_value.startswith(parsed.scheme)
            or parsed.path
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise forms.ValidationError(error_message)
        if DeniedInstallOrigin.find_denied_origins([value]):
            raise forms.ValidationError(
                DeniedInstallOrigin.ERROR_MESSAGE.format(origin=value)
            )
        return value
