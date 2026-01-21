import itertools
import os
import tarfile
import zipfile
from functools import cached_property
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db.models import Q
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.forms.widgets import RadioSelect
from django.urls import reverse
from django.utils.functional import keep_lazy_text
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import get_language, gettext, gettext_lazy as _, ngettext

import waffle
from django_statsd.clients import statsd

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons import tasks as addons_tasks
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonCategory,
    AddonListingInfo,
    AddonUser,
    AddonUserPendingConfirmation,
    DeniedSlug,
    Preview,
)
from olympia.addons.utils import remove_icons, validate_addon_name
from olympia.amo.enum import StrEnumChoices
from olympia.amo.fields import HttpHttpsOnlyURLField, ReCaptchaField
from olympia.amo.forms import AMOModelForm
from olympia.amo.messages import DoubleSafe
from olympia.amo.utils import slug_validator, verify_no_urls
from olympia.amo.validators import OneOrMoreLetterOrNumberCharacterValidator
from olympia.api.models import APIKey, APIKeyConfirmation
from olympia.api.throttling import CheckThrottlesFormMixin, addon_submission_throttles
from olympia.applications.models import AppVersion
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.devhub.widgets import CategoriesSelectMultiple, IconTypeSelect
from olympia.files.models import FileUpload
from olympia.files.utils import SafeTar, SafeZip, parse_addon
from olympia.scanners.tasks import run_narc_on_version
from olympia.tags.models import Tag
from olympia.translations import LOCALES
from olympia.translations.fields import LocaleErrorMessage, TransField, TransTextarea
from olympia.translations.forms import TranslationFormMixin
from olympia.translations.models import Translation, delete_translation
from olympia.translations.utils import (
    fetch_translations_from_instance,
    get_translation_differences,
)
from olympia.translations.widgets import TranslationTextarea, TranslationTextInput
from olympia.users.models import (
    RESTRICTION_TYPES,
    EmailUserRestriction,
    UserEmailField,
    UserProfile,
)
from olympia.users.utils import RestrictionChecker
from olympia.versions.compare import version_int
from olympia.versions.models import (
    VALID_SOURCE_EXTENSIONS,
    ApplicationsVersions,
    License,
    Version,
)
from olympia.versions.utils import (
    validate_version_number_does_not_exist,
    validate_version_number_is_gt_latest_signed_listed_version,
)


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


class AddonFormBase(TranslationFormMixin, AMOModelForm):
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

    def clean_summary(self):
        summary = verify_no_urls(
            self.cleaned_data['summary'], form=self, field_name='summary'
        )
        return summary

    def clean_name(self):
        user = getattr(self.request, 'user', None)

        name = validate_addon_name(self.cleaned_data['name'], user, form=self)

        return name

    def save(self, *args, **kwargs):
        metadata_content_review = self.instance and self.instance.has_listed_versions()
        existing_data = (
            fetch_translations_from_instance(
                self.instance, self.fields_to_trigger_content_review
            )
            if metadata_content_review
            else {}
        )
        obj = super().save(*args, **kwargs)
        if metadata_content_review:
            new_data = fetch_translations_from_instance(
                obj, self.fields_to_trigger_content_review
            )
            if existing_data != new_data:
                self.metadata_changes = get_translation_differences(
                    existing_data, new_data
                )
                # flag for content review
                statsd.incr('devhub.metadata_content_review_triggered')
                AddonApprovalsCounter.reset_content_for_addon(addon=obj)
                AddonListingInfo.maybe_mark_as_noindexed(addon=obj)

                if (
                    waffle.switch_is_active('enable-narc')
                    and 'name' in self.metadata_changes
                    and (
                        version
                        := self.instance.find_latest_non_rejected_listed_version()
                    )
                ):
                    run_narc_on_version.delay(version.pk)

        return obj


class CategoryForm(forms.Form):
    categories = forms.MultipleChoiceField(choices=(), widget=CategoriesSelectMultiple)

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request', None)
        super().__init__(*args, **kw)
        cats = sorted(
            CATEGORIES.get(self.addon.type, {}).values(),
            key=lambda x: x.name,
        )
        if self.addon.type == amo.ADDON_STATICTHEME:
            self.max_categories = 1
            self.fields['categories'] = forms.ChoiceField(widget=forms.RadioSelect)
        else:
            self.max_categories = amo.MAX_CATEGORIES
        self.fields['categories'].choices = [(c.id, c.name) for c in cats]
        self.fields['categories'].initial = [c.id for c in self.addon.all_categories]

    def save(self):
        categories_new = [int(c) for c in self.cleaned_data['categories']]
        categories_old = [c.id for c in self.addon.all_categories]

        # Add new categories.
        for c_id in set(categories_new) - set(categories_old):
            AddonCategory(addon=self.addon, category_id=c_id).save()

        # Remove old categories.
        for c_id in set(categories_old) - set(categories_new):
            AddonCategory.objects.filter(addon=self.addon, category_id=c_id).delete()

        # Remove old, outdated categories cache on the model.
        del self.addon.all_categories

        # Make sure the add-on is properly re-indexed
        addons_tasks.index_addons.delay([self.addon.id])

    def clean_categories(self):
        categories = self.cleaned_data['categories']
        if isinstance(categories, str):
            categories = [categories]
        total = len(categories)

        if total > self.max_categories:
            # L10n: {0} is the number of categories.
            raise forms.ValidationError(
                ngettext(
                    'You can have only {0} category.',
                    'You can have only {0} categories.',
                    self.max_categories,
                ).format(self.max_categories)
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
            remove_icons(addon)
            addons_tasks.resize_icon.delay(
                upload_path,
                addon.pk,
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
    contributions = HttpHttpsOnlyURLField(required=False)

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

            if hostname not in amo.VALID_CONTRIBUTION_DOMAINS:
                raise forms.ValidationError(
                    gettext('URL domain must be one of [%s].')
                    % ', '.join(amo.VALID_CONTRIBUTION_DOMAINS)
                )
            elif hostname == 'github.com' and not path.startswith('/sponsors/'):
                # Issue 15497, validate path for GitHub Sponsors
                raise forms.ValidationError(
                    gettext('URL path for GitHub Sponsors must contain /sponsors/.')
                )
            elif parsed_url.scheme != 'https':
                raise forms.ValidationError(gettext('URLs must start with https://.'))
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


class AuthorForm(AMOModelForm):
    user = UserEmailField(
        required=True,
        queryset=UserProfile.objects.all(),
    )
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
    # In order to be invited a user profile needs to be non-deleted and have a
    # fxa_id (ensuring they logged in at least once through FxA).
    user = UserEmailField(
        required=True,
        queryset=UserProfile.objects.filter(fxa_id__isnull=False)
        .exclude(deleted=True)
        .order_by('created'),
    )

    class Meta(AuthorForm.Meta):
        model = AddonUserPendingConfirmation

    def clean_user(self):
        user = self.cleaned_data.get('user')
        if user:
            if not EmailUserRestriction.allow_email(
                user.email, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
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
            except forms.ValidationError as exc:
                raise forms.ValidationError(
                    gettext(
                        'The account needs a display name before it can be added '
                        'as an author.'
                    )
                ) from exc
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
        licenses = License.objects.builtins(cc=self.cc_licenses, on_form=True)
        choices = [(x.builtin, x) for x in licenses]
        if not self.cc_licenses:
            # creative commons licenses don't have an 'other' option.
            choices.append((License.OTHER, gettext('Other')))
        if (
            self.version
            and self.version.license
            and self.version.license.builtin
            and self.version.license.builtin not in amo.FORM_LICENSES
        ):
            # Special case where the version has an old deprecated license that
            # was built-in but is no longer displayed on the form by default.
            choices.append((self.version.license.builtin, self.version.license))
        self.fields['builtin'].choices = choices
        if self.version and self.version.channel == amo.CHANNEL_UNLISTED:
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
                    ActivityLog.objects.create(
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
        label=_("Please specify your add-on's End-User License Agreement:"),
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
        for has, field in (('has_eula', 'eula'), ('has_priv', 'privacy_policy')):
            if not self.cleaned_data[has]:
                delete_translation(self.instance, field)

        return ob


class WithSourceMixin:
    def get_invalid_source_file_type_message(self):
        valid_extensions_string = '(%s)' % ', '.join(VALID_SOURCE_EXTENSIONS)
        return gettext(
            'Unsupported file type, please upload an archive file {extensions}.'.format(
                extensions=valid_extensions_string
            )
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
                    # For zip files, opening them though SafeZip() checks that
                    # we can accept the file and testzip() on top of that
                    # returns None if there are no broken CRCs.
                    zip_file = SafeZip(source)
                    if zip_file.zip_file.testzip() is not None:
                        raise zipfile.BadZipFile()
                elif source.name.endswith(('.tar.gz', '.tar.bz2', '.tgz')):
                    # For tar files, opening them through SafeTar.open() checks
                    # that we can accept it.
                    mode = 'r:bz2' if source.name.endswith('bz2') else 'r:gz'
                    with SafeTar.open(mode=mode, fileobj=source):
                        pass
                else:
                    raise forms.ValidationError(
                        self.get_invalid_source_file_type_message()
                    )
            except (zipfile.BadZipFile, tarfile.ReadError, OSError, EOFError) as exc:
                raise forms.ValidationError(
                    gettext('Invalid or broken archive.')
                ) from exc
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


class VersionForm(TranslationFormMixin, WithSourceMixin, AMOModelForm):
    release_notes = TransField(widget=TransTextarea(), required=False)
    approval_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4}),
        required=False,
    )
    source = forms.FileField(required=False, widget=SourceFileInput)

    class Meta:
        model = Version
        fields = (
            'release_notes',
            'approval_notes',
            'source',
        )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.human_review_date and not self.instance.pending_rejection:
            self.fields['source'].disabled = True


class AppVersionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # Return the object instead of transforming into a label at this stage
        # so that it's available in the widget. When converted to a string it
        # will be the version number anyway.
        return obj


class AppVersionChoiceWidget(forms.Select):
    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        obj = label  # See AppVersionChoiceField.label_from_instance()
        disable_between = getattr(
            self, 'disable_between', ()
        )  # See CompatForm.__init__()
        rval = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        if (
            len(disable_between) == 2
            and obj
            and isinstance(obj, AppVersion)
            and obj.version_int >= version_int(disable_between[0])
            and obj.version_int < version_int(disable_between[1])
        ):
            rval['attrs']['disabled'] = 'disabled'
        return rval


class CompatForm(AMOModelForm):
    application = forms.TypedChoiceField(
        choices=amo.APPS_CHOICES, coerce=int, widget=forms.HiddenInput
    )
    min = AppVersionChoiceField(
        AppVersion.objects.none(), widget=AppVersionChoiceWidget
    )
    max = AppVersionChoiceField(
        AppVersion.objects.none(), widget=AppVersionChoiceWidget
    )

    class Meta:
        model = ApplicationsVersions
        fields = ('application', 'min', 'max')

    def __init__(self, *args, **kwargs):
        # 'version' should always be passed as a kwarg to this form. If it's
        # absent, it probably means form_kwargs={'version': version} is missing
        # from the instantiation of the formset.
        self.version = kwargs.pop('version')
        addon = self.version.addon
        super().__init__(*args, **kwargs)
        if self.initial:
            app = self.initial['application']
        else:
            app = self.data[self.add_prefix('application')]
        self.app = amo.APPS_ALL[int(app)]
        qs = AppVersion.objects.filter(application=app).order_by('version_int')

        self.fields['min'].queryset = qs.filter(~Q(version__contains='*'))
        self.fields['max'].queryset = qs.all()

        if self.instance.locked_from_manifest:
            for field in self.fields.values():
                field.disabled = True
                field.required = False

        # On Android, disable Fenix-pre GA version range unless the add-on is
        # recommended or line.
        if (
            app == amo.ANDROID.id
            and not addon.can_be_compatible_with_all_fenix_versions
        ):
            self.fields[
                'min'
            ].widget.disable_between = (
                ApplicationsVersions.ANDROID_LIMITED_COMPATIBILITY_RANGE
            )
            self.fields[
                'max'
            ].widget.disable_between = (
                ApplicationsVersions.ANDROID_LIMITED_COMPATIBILITY_RANGE
            )

    def clean(self):
        min_ = self.cleaned_data.get('min')
        max_ = self.cleaned_data.get('max')
        if not self.instance.locked_from_manifest:
            if min_ and max_ and min_.version_int > max_.version_int:
                raise forms.ValidationError(gettext('Invalid version range.'))
            if self.instance.application:
                self.cleaned_data['application'] = self.instance.application
        # Build a temporary instance with cleaned data to make it easier to
        # check range validity.
        if min_ and max_:
            avs = ApplicationsVersions(
                application=self.cleaned_data['application'],
                min=min_,
                max=max_,
                version=self.version,
            )
            if (
                avs.application == amo.ANDROID.id
                and avs.version_range_contains_forbidden_compatibility()
            ):
                valid_range = ApplicationsVersions.ANDROID_LIMITED_COMPATIBILITY_RANGE
                raise forms.ValidationError(
                    gettext(
                        'Invalid version range. For Firefox for Android, you may only '
                        'pick a range that starts with version %(max)s or higher, '
                        'or ends with lower than version %(min)s.'
                    )
                    % {'min': valid_range[0], 'max': valid_range[1]}
                )
        return self.cleaned_data


class BaseCompatFormSet(BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We always want a form for each app, so force extras for apps
        # the add-on does not already have.
        version = self.form_kwargs['version']
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
        self.forms  # noqa: B018

    def add_fields(self, form, index):
        # By default django handles can_delete globally for the whole formset,
        # we want to do it per-form so we override the function that adds the
        # delete button.
        original_can_delete = self.can_delete
        if self.can_delete and form.instance and form.instance.locked_from_manifest:
            self.can_delete = False
        super().add_fields(form, index)
        self.can_delete = original_can_delete

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


class NewUploadForm(CheckThrottlesFormMixin, forms.Form):
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
    theme_specific = forms.BooleanField(required=False, widget=forms.HiddenInput)

    throttled_error_message = _(
        'You have submitted too many uploads recently. '
        'Please try again after some time.'
    )
    throttle_classes = addon_submission_throttles
    recaptcha = ReCaptchaField(label='')

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        self.addon = kw.pop('addon', None)
        self.include_recaptcha = kw.pop('include_recaptcha', False)
        super().__init__(*args, **kw)

        recaptcha_enabled = waffle.switch_is_active('developer-submit-addon-captcha')
        if not recaptcha_enabled or not self.include_recaptcha:
            del self.fields['recaptcha']

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
            and acl.action_allowed_for(self.request.user, amo.permissions.REVIEWS_ADMIN)
        ):
            raise forms.ValidationError(
                gettext('There was an error with your upload. Please try again.')
            )

    def check_for_existing_versions(self, version_string):
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
            raise forms.ValidationError(msg.format(version=version))

    def clean(self):
        super().clean()

        if not self.errors:
            self._clean_upload()
            parsed_data = parse_addon(
                self.cleaned_data['upload'], addon=self.addon, user=self.request.user
            )

            if self.addon:
                self.check_for_existing_versions(parsed_data.get('version'))
                if self.cleaned_data['upload'].channel == amo.CHANNEL_LISTED:
                    if error_message := (
                        validate_version_number_is_gt_latest_signed_listed_version(
                            self.addon, parsed_data.get('version')
                        )
                    ):
                        raise forms.ValidationError(error_message)

            self.cleaned_data['parsed_data'] = parsed_data
        return self.cleaned_data


class SourceForm(WithSourceMixin, AMOModelForm):
    source = forms.FileField(
        required=False,
        widget=SourceFileInput(
            attrs={'data-max-upload-size': settings.MAX_UPLOAD_SIZE}
        ),
    )
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
    name = TransField()
    slug = forms.CharField()
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}))
    description = TransField(
        widget=TransTextarea(attrs={'rows': 6}),
        min_length=10,
    )
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
                        self.cleaned_data.setdefault('summary', {})[locale] = (
                            summary_values[locale][:max_summary_length]
                        )
        return self.cleaned_data


class DescribeFormContentOptimization(CombinedNameSummaryCleanMixin, DescribeForm):
    name = TransField(min_length=2, max_length=255)
    summary = TransField(min_length=2, max_length=255)


class DescribeFormUnlisted(AddonFormBase):
    name = TransField()
    slug = forms.CharField()
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}))
    description = TransField(widget=TransTextarea(attrs={'rows': 4}), required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'description')


class DescribeFormUnlistedContentOptimization(
    CombinedNameSummaryCleanMixin, DescribeFormUnlisted
):
    name = TransField(max_length=68, min_length=2)
    summary = TransField(max_length=68, min_length=2)


class PreviewForm(TranslationFormMixin, AMOModelForm):
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
                addons_tasks.resize_preview.delay(
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


class APIKeyForm(forms.Form):
    class ACTION_CHOICES(StrEnumChoices):
        CONFIRM = 'confirm', _('Confirm email address')
        GENERATE = 'generate', _('Generate new credentials')
        REGENERATE = 'regenerate', _('Revoke and regenerate credentials')
        REVOKE = 'revoke', _('Revoke')

    ACTION_CHOICES.add_subset('REQUIRES_CREDENTIALS', ('REVOKE', 'REGENERATE'))
    ACTION_CHOICES.add_subset('REQUIRES_CONFIRMATION', ('GENERATE', 'REGENERATE'))

    @cached_property
    def credentials(self):
        try:
            return APIKey.get_jwt_key(user=self.request.user)
        except APIKey.DoesNotExist:
            return None

    @cached_property
    def confirmation(self):
        try:
            return APIKeyConfirmation.objects.get(user=self.request.user)
        except APIKeyConfirmation.DoesNotExist:
            return None

    def validate_confirmation_token(self, value):
        if (
            not self.confirmation.confirmed_once
            and not self.confirmation.is_token_valid(value)
        ):
            raise forms.ValidationError('Invalid token')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self.action = self.data.get('action', None)
        self.available_actions = []

        # Available actions determine what you can do currently
        has_credentials = self.credentials is not None
        has_confirmation = self.confirmation is not None

        # User has credentials, show them and offer to revoke/regenerate
        if has_credentials:
            self.fields['credentials_key'] = forms.CharField(
                label=_('JWT issuer'),
                max_length=255,
                disabled=True,
                widget=forms.TextInput(attrs={'readonly': True}),
                required=True,
                initial=self.credentials.key,
                help_text=_(
                    'To make API requests, send a <a href="{jwt_url}">'
                    'JSON Web Token (JWT)</a> as the authorization header. '
                    "You'll need to generate a JWT for every request as explained in "
                    'the <a href="{docs_url}">API documentation</a>.'
                ).format(
                    jwt_url='https://self-issued.info/docs/draft-ietf-oauth-json-web-token.html',
                    docs_url='https://addons-server.readthedocs.io/en/latest/topics/api/auth.html',
                ),
            )
            self.fields['credentials_secret'] = forms.CharField(
                label=_('JWT secret'),
                max_length=255,
                disabled=True,
                widget=forms.TextInput(attrs={'readonly': True}),
                required=True,
                initial=self.credentials.secret,
            )
            self.available_actions.append(self.ACTION_CHOICES.REVOKE)

            if has_confirmation and self.confirmation.confirmed_once:
                self.available_actions.append(self.ACTION_CHOICES.REGENERATE)

        elif has_confirmation:
            get_token_param = self.request.GET.get('token')

            if (
                self.confirmation.confirmed_once
                or get_token_param is not None
                or self.data.get('confirmation_token') is not None
            ):
                help_text = _(
                    'Please click the confirm button below to generate '
                    'API credentials for user <strong>{name}</strong>.'
                ).format(name=self.request.user.name)
                self.available_actions.append(self.ACTION_CHOICES.GENERATE)
            else:
                help_text = _(
                    'A confirmation link will be sent to your email address. '
                    'After confirmation you will find your API keys on this page.'
                )

            self.fields['confirmation_token'] = forms.CharField(
                label='',
                max_length=20,
                widget=forms.HiddenInput(),
                initial=get_token_param,
                required=False,
                help_text=help_text,
                validators=[self.validate_confirmation_token],
            )

        else:
            if waffle.switch_is_active('developer-submit-addon-captcha'):
                self.fields['recaptcha'] = ReCaptchaField(
                    label='', help_text=_("You don't have any API credentials.")
                )
            self.available_actions.append(self.ACTION_CHOICES.CONFIRM)

    def clean(self):
        cleaned_data = super().clean()

        # The actions available depend on the current state
        # and are determined during initialization
        if self.action not in self.available_actions:
            raise forms.ValidationError(
                _('Something went wrong, please contact developer support.')
            )

        return cleaned_data

    def save(self):
        credentials_revoked = False
        credentials_generated = False
        confirmation_created = False

        # User is revoking or regenerating credentials, revoke existing credentials
        if self.action in self.ACTION_CHOICES.REQUIRES_CREDENTIALS:
            self.credentials.update(is_active=None)
            credentials_revoked = True

        # user is trying to generate or regenerate credentials, create new credentials
        if self.action in self.ACTION_CHOICES.REQUIRES_CONFIRMATION:
            self.confirmation.update(confirmed_once=True)
            self.credentials = APIKey.new_jwt_credentials(self.request.user)
            credentials_generated = True

        # user has no credentials or confirmation, create a confirmation
        if self.action == self.ACTION_CHOICES.CONFIRM:
            self.confirmation = APIKeyConfirmation.objects.create(
                user=self.request.user, token=APIKeyConfirmation.generate_token()
            )
            confirmation_created = True

        return {
            'credentials_revoked': credentials_revoked,
            'credentials_generated': credentials_generated,
            'confirmation_created': confirmation_created,
        }


class LimitedModelChoiceField(forms.ModelChoiceField):
    limit_choice_count = 100  # django docs suggest 100 is the max you should use

    def __init__(self, queryset, *, limit_choice_count, **kwargs):
        self.limit_choice_count = limit_choice_count
        super().__init__(queryset, **kwargs)

    def _set_queryset(self, queryset):
        if hasattr(self, '_choices'):
            del self._choices
        super()._set_queryset(queryset)

    queryset = property(forms.ModelChoiceField._get_queryset, _set_queryset)

    def _get_choices(self):
        # If self._choices is set, we called this before.
        if hasattr(self, '_choices'):
            return self._choices

        count = self.limit_choice_count + (1 if self.empty_label else 0)
        # We need to limit the choices, but we can't slice the queryset.
        self._choices = list(itertools.islice(self.iterator(self), count))
        return self._choices

    choices = property(_get_choices, forms.ModelChoiceField._set_choices)


class RollbackVersionForm(forms.Form):
    """
    Form to rollback a version to a previous one.
    """

    channel = forms.TypedChoiceField(
        choices=(
            (
                amo.CHANNEL_LISTED,
                mark_safe('<span class="distribution-tag-listed">AMO</span>'),
            ),
            (
                amo.CHANNEL_UNLISTED,
                mark_safe('<span class="distribution-tag-unlisted">Self</span>'),
            ),
        ),
        coerce=int,
        widget=forms.RadioSelect(),
    )
    listed_version = LimitedModelChoiceField(
        queryset=Version.objects.none(),
        empty_label=_('No appropriate version available'),
        required=False,
        # We currently only allow rolling back to a single listed version.
        limit_choice_count=1,
    )
    unlisted_version = LimitedModelChoiceField(
        queryset=Version.objects.none(),
        empty_label=_('Choose version'),
        required=False,
        limit_choice_count=25,
    )
    new_version_string = forms.CharField(max_length=255)
    release_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        max_length=255,
        required=False,
        label=_('Release notes'),
        initial=_('Automatic rollback based on version [m.m].'),
    )

    def __init__(self, *args, **kwargs):
        self.addon = kwargs.pop('addon')
        super().__init__(*args, **kwargs)
        listed = self.fields['listed_version']
        unlisted = self.fields['unlisted_version']
        channel = self.fields['channel']

        listed.queryset = self.addon.rollbackable_versions_qs(
            amo.CHANNEL_LISTED
        ).no_transforms()
        self.has_listed = bool(len(listed.choices) - 1)  # Skip empty_label

        if self.has_listed:
            # drop empty label
            listed.choices.pop(0)
            self.empty_label = None

        unlisted.queryset = self.addon.rollbackable_versions_qs(
            amo.CHANNEL_UNLISTED
        ).no_transforms()
        self.has_unlisted = bool(len(unlisted.choices) - 1)  # Skip empty_label

        if not self.has_listed and self.has_unlisted:
            # if there is no listed option, we default to unlisted
            channel.initial = amo.CHANNEL_UNLISTED
            channel.disabled = True
        elif not self.has_unlisted and self.has_listed:
            # if there is a listed option, we default to that channel
            channel.initial = amo.CHANNEL_LISTED
            channel.disabled = True
        elif self.has_listed or self.has_unlisted:
            # otherwise we default to the most recently used channel
            channel.initial = self.addon.versions.values_list('channel', flat=True)[0]
        # Also, in the template, we hide the selector if there is only one channel,
        # using a hidden input

    def clean_new_version_string(self):
        new_version_string = self.cleaned_data.get('new_version_string')
        channel = self.cleaned_data.get('channel')
        if error := validate_version_number_does_not_exist(
            self.addon, new_version_string
        ):
            raise forms.ValidationError(error)

        if channel == amo.CHANNEL_LISTED and (
            error := validate_version_number_is_gt_latest_signed_listed_version(
                self.addon, new_version_string
            )
        ):
            raise forms.ValidationError(error)
        return new_version_string

    def clean_release_notes(self):
        notes = self.cleaned_data.get('release_notes', '').strip()
        self.cleaned_data['release_notes'] = {self.addon.default_locale.lower(): None}
        if notes:
            self.cleaned_data['release_notes'][get_language()] = notes
        return self.cleaned_data['release_notes']

    def clean(self):
        data = super().clean()
        data['version'] = (
            data.get('listed_version')
            if data.get('channel') == amo.CHANNEL_LISTED
            else data.get('unlisted_version')
            if data.get('channel') == amo.CHANNEL_UNLISTED
            else None
        )
        if not data['version']:
            raise forms.ValidationError(
                gettext('You must select a channel and version to rollback to.')
            )
        return data

    def can_rollback(self):
        return self.has_listed or self.has_unlisted
