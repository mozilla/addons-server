import os

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.forms.formsets import BaseFormSet, formset_factory
from django.utils.encoding import force_text
from django.utils.translation import ugettext, ungettext

import waffle
from six.moves.urllib_parse import urlsplit

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons import tasks as addons_tasks
from olympia.addons.models import Addon, AddonCategory, Category, DeniedSlug
from olympia.addons.widgets import CategoriesSelectMultiple, IconTypeSelect
from olympia.addons.utils import verify_mozilla_trademark
from olympia.amo.fields import HttpHttpsOnlyURLField, ReCaptchaField
from olympia.amo.utils import (
    remove_icons, slug_validator, slugify, sorted_groupby)
from olympia.amo.validators import OneOrMoreLetterOrNumberCharacterValidator
from olympia.devhub import tasks as devhub_tasks
from olympia.devhub.utils import (
    fetch_existing_translations_from_addon, get_addon_akismet_reports)
from olympia.tags.models import Tag
from olympia.translations import LOCALES
from olympia.translations.fields import TransField, TransTextarea
from olympia.translations.forms import TranslationFormMixin
from olympia.translations.models import Translation


log = olympia.core.logger.getLogger('z.addons')


def clean_addon_slug(slug, instance):
    slug_validator(slug, lower=False)

    if slug != instance.slug:
        if Addon.objects.filter(slug=slug).exists():
            raise forms.ValidationError(ugettext(
                'This slug is already in use. Please choose another.'))
        if DeniedSlug.blocked(slug):
            msg = ugettext(u'The slug cannot be "%(slug)s". '
                           u'Please choose another.')
            raise forms.ValidationError(msg % {'slug': slug})

    return slug


def clean_tags(request, tags):
    target = [slugify(t, spaces=True, lower=True) for t in tags.split(',')]
    target = set(filter(None, target))

    min_len = amo.MIN_TAG_LENGTH
    max_len = Tag._meta.get_field('tag_text').max_length
    max_tags = amo.MAX_TAGS
    total = len(target)

    denied = (Tag.objects.values_list('tag_text', flat=True)
              .filter(tag_text__in=target, denied=True))
    if denied:
        # L10n: {0} is a single tag or a comma-separated list of tags.
        msg = ungettext('Invalid tag: {0}', 'Invalid tags: {0}',
                        len(denied)).format(', '.join(denied))
        raise forms.ValidationError(msg)

    restricted = (Tag.objects.values_list('tag_text', flat=True)
                     .filter(tag_text__in=target, restricted=True))
    if not acl.action_allowed(request, amo.permissions.ADDONS_EDIT):
        if restricted:
            # L10n: {0} is a single tag or a comma-separated list of tags.
            msg = ungettext('"{0}" is a reserved tag and cannot be used.',
                            '"{0}" are reserved tags and cannot be used.',
                            len(restricted)).format('", "'.join(restricted))
            raise forms.ValidationError(msg)
    else:
        # Admin's restricted tags don't count towards the limit.
        total = len(target - set(restricted))

    if total > max_tags:
        num = total - max_tags
        msg = ungettext('You have {0} too many tags.',
                        'You have {0} too many tags.', num).format(num)
        raise forms.ValidationError(msg)

    if any(t for t in target if len(t) > max_len):
        raise forms.ValidationError(
            ugettext(
                'All tags must be %s characters or less after invalid '
                'characters are removed.' % max_len))

    if any(t for t in target if len(t) < min_len):
        msg = ungettext('All tags must be at least {0} character.',
                        'All tags must be at least {0} characters.',
                        min_len).format(min_len)
        raise forms.ValidationError(msg)

    return target


class AkismetSpamCheckFormMixin(object):
    fields_to_akismet_comment_check = []

    def clean(self):
        data = {
            prop: value for prop, value in self.cleaned_data.items()
            if prop in self.fields_to_akismet_comment_check}
        request_meta = getattr(self.request, 'META', {})

        # Find out if there is existing metadata that's been spam checked.
        addon_listed_versions = self.instance.versions.filter(
            channel=amo.RELEASE_CHANNEL_LISTED)
        if self.version:
            # If this is in the submission flow, exclude version in progress.
            addon_listed_versions = addon_listed_versions.exclude(
                id=self.version.id)
        existing_data = (
            fetch_existing_translations_from_addon(
                self.instance, self.fields_to_akismet_comment_check)
            if addon_listed_versions.exists() else ())

        reports = get_addon_akismet_reports(
            user=getattr(self.request, 'user', None),
            user_agent=request_meta.get('HTTP_USER_AGENT'),
            referrer=request_meta.get('HTTP_REFERER'),
            addon=self.instance,
            data=data,
            existing_data=existing_data)
        error_msg = ugettext('The text entered has been flagged as spam.')
        error_if_spam = waffle.switch_is_active('akismet-addon-action')
        for prop, report in reports:
            is_spam = report.is_spam
            if error_if_spam and is_spam:
                self.add_error(prop, forms.ValidationError(error_msg))
        return super(AkismetSpamCheckFormMixin, self).clean()


class AddonFormBase(TranslationFormMixin, forms.ModelForm):

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        self.version = kw.pop('version', None)
        super(AddonFormBase, self).__init__(*args, **kw)
        for field in ('name', 'summary'):
            if field in self.fields:
                self.fields[field].validators.append(
                    OneOrMoreLetterOrNumberCharacterValidator())

    class Meta:
        models = Addon
        fields = ('name', 'slug', 'summary', 'tags')

    def clean_slug(self):
        return clean_addon_slug(self.cleaned_data['slug'], self.instance)

    def clean_name(self):
        user = getattr(self.request, 'user', None)

        name = verify_mozilla_trademark(
            self.cleaned_data['name'], user,
            form=self)

        return name

    def clean_tags(self):
        return clean_tags(self.request, self.cleaned_data['tags'])

    def get_tags(self, addon):
        if acl.action_allowed(self.request, amo.permissions.ADDONS_EDIT):
            return list(addon.tags.values_list('tag_text', flat=True))
        else:
            return list(addon.tags.filter(restricted=False)
                        .values_list('tag_text', flat=True))


class CategoryForm(forms.Form):
    application = forms.TypedChoiceField(
        choices=amo.APPS_CHOICES, coerce=int, widget=forms.HiddenInput,
        required=True)
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(), widget=CategoriesSelectMultiple)

    def save(self, addon):
        application = self.cleaned_data.get('application')
        categories_new = [c.id for c in self.cleaned_data['categories']]
        categories_old = [
            c.id for c in
            addon.app_categories.get(amo.APP_IDS[application].short, [])]

        # Add new categories.
        for c_id in set(categories_new) - set(categories_old):
            AddonCategory(addon=addon, category_id=c_id).save()

        # Remove old categories.
        for c_id in set(categories_old) - set(categories_new):
            AddonCategory.objects.filter(
                addon=addon, category_id=c_id).delete()

        # Remove old, outdated categories cache on the model.
        del addon.all_categories

        # Make sure the add-on is properly re-indexed
        addons_tasks.index_addons.delay([addon.id])

    def clean_categories(self):
        categories = self.cleaned_data['categories']
        total = categories.count()
        max_cat = amo.MAX_CATEGORIES

        if getattr(self, 'disabled', False) and total:
            raise forms.ValidationError(ugettext(
                'Categories cannot be changed while your add-on is featured '
                'for this application.'))
        if total > max_cat:
            # L10n: {0} is the number of categories.
            raise forms.ValidationError(ungettext(
                'You can have only {0} category.',
                'You can have only {0} categories.',
                max_cat).format(max_cat))

        has_misc = list(filter(lambda x: x.misc, categories))
        if has_misc and total > 1:
            raise forms.ValidationError(ugettext(
                'The miscellaneous category cannot be combined with '
                'additional categories.'))

        return categories


class BaseCategoryFormSet(BaseFormSet):

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request', None)
        super(BaseCategoryFormSet, self).__init__(*args, **kw)
        self.initial = []
        apps = sorted(self.addon.compatible_apps.keys(), key=lambda x: x.id)

        # Drop any apps that don't have appropriate categories.
        qs = Category.objects.filter(type=self.addon.type)
        app_cats = {k: list(v) for k, v in sorted_groupby(qs, 'application')}
        for app in list(apps):
            if app and not app_cats.get(app.id):
                apps.remove(app)
        if not app_cats:
            apps = []

        for app in apps:
            cats = self.addon.app_categories.get(app.short, [])
            self.initial.append({'categories': [c.id for c in cats]})

        for app, form in zip(apps, self.forms):
            key = app.id if app else None
            form.request = self.request
            form.initial['application'] = key
            form.app = app
            cats = sorted(app_cats[key], key=lambda x: x.name)
            form.fields['categories'].choices = [(c.id, c.name) for c in cats]

            # If this add-on is featured for this application, category
            # changes are forbidden.
            if not acl.action_allowed(self.request,
                                      amo.permissions.ADDONS_EDIT):
                form.disabled = (app and self.addon.is_featured(app))

    def save(self):
        for f in self.forms:
            f.save(self.addon)


CategoryFormSet = formset_factory(form=CategoryForm,
                                  formset=BaseCategoryFormSet, extra=0)


def icons():
    """
    Generates a list of tuples for the default icons for add-ons,
    in the format (pseudo-mime-type, description).
    """
    icons = [('image/jpeg', 'jpeg'), ('image/png', 'png'), ('', 'default')]
    dirs, files = storage.listdir(settings.ADDON_ICONS_DEFAULT_PATH)
    for fname in files:
        if b'32' in fname and b'default' not in fname:
            icon_name = force_text(fname.split(b'-')[0])
            icons.append(('icon/%s' % icon_name, icon_name))
    return sorted(icons)


class AddonFormMedia(AddonFormBase):
    icon_type = forms.CharField(widget=IconTypeSelect(
        choices=[]), required=False)
    icon_upload_hash = forms.CharField(required=False)

    class Meta:
        model = Addon
        fields = ('icon_upload_hash', 'icon_type')

    def __init__(self, *args, **kwargs):
        super(AddonFormMedia, self).__init__(*args, **kwargs)

        # Add icons here so we only read the directory when
        # AddonFormMedia is actually being used.
        self.fields['icon_type'].widget.choices = icons()

    def save(self, addon, commit=True):
        if self.cleaned_data['icon_upload_hash']:
            upload_hash = self.cleaned_data['icon_upload_hash']
            upload_path = os.path.join(settings.TMP_PATH, 'icon', upload_hash)

            dirname = addon.get_icon_dir()
            destination = os.path.join(dirname, '%s' % addon.id)

            remove_icons(destination)
            devhub_tasks.resize_icon.delay(
                upload_path, destination, amo.ADDON_ICON_SIZES,
                set_modified_on=addon.serializable_reference())

        return super(AddonFormMedia, self).save(commit)


class AdditionalDetailsForm(AddonFormBase):
    default_locale = forms.TypedChoiceField(choices=LOCALES)
    homepage = TransField.adapt(HttpHttpsOnlyURLField)(required=False)
    tags = forms.CharField(required=False)
    contributions = HttpHttpsOnlyURLField(required=False, max_length=255)

    class Meta:
        model = Addon
        fields = ('default_locale', 'homepage', 'tags', 'contributions')

    def __init__(self, *args, **kw):
        super(AdditionalDetailsForm, self).__init__(*args, **kw)

        if self.fields.get('tags'):
            self.fields['tags'].initial = ', '.join(
                self.get_tags(self.instance))

    def clean_contributions(self):
        if self.cleaned_data['contributions']:
            hostname = urlsplit(self.cleaned_data['contributions']).hostname
            if not hostname.endswith(amo.VALID_CONTRIBUTION_DOMAINS):
                raise forms.ValidationError(ugettext(
                    'URL domain must be one of [%s], or a subdomain.'
                ) % ', '.join(amo.VALID_CONTRIBUTION_DOMAINS))
        return self.cleaned_data['contributions']

    def clean(self):
        # Make sure we have the required translations in the new locale.
        required = 'name', 'summary', 'description'
        if not self.errors and 'default_locale' in self.changed_data:
            fields = dict((k, getattr(self.instance, k + '_id'))
                          for k in required)
            locale = self.cleaned_data['default_locale']
            ids = filter(None, fields.values())
            qs = (Translation.objects.filter(locale=locale, id__in=ids,
                                             localized_string__isnull=False)
                  .values_list('id', flat=True))
            missing = [k for k, v in fields.items() if v not in qs]
            if missing:
                raise forms.ValidationError(ugettext(
                    'Before changing your default locale you must have a '
                    'name, summary, and description in that locale. '
                    'You are missing %s.') % ', '.join(map(repr, missing)))
        return super(AdditionalDetailsForm, self).clean()

    def save(self, addon, commit=False):
        if self.fields.get('tags'):
            tags_new = self.cleaned_data['tags']
            tags_old = [slugify(t, spaces=True) for t in self.get_tags(addon)]

            # Add new tags.
            for t in set(tags_new) - set(tags_old):
                Tag(tag_text=t).save_tag(addon)

            # Remove old tags.
            for t in set(tags_old) - set(tags_new):
                Tag(tag_text=t).remove_tag(addon)

        # We ignore `commit`, since we need it to be `False` so we can save
        # the ManyToMany fields on our own.
        addonform = super(AdditionalDetailsForm, self).save(commit=False)
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
        fields = ('developer_comments', 'view_source', 'public_stats')


class AddonFormTechnicalUnlisted(AddonFormBase):
    class Meta:
        model = Addon
        fields = ()


class AbuseForm(forms.Form):
    recaptcha = ReCaptchaField(label='')
    text = forms.CharField(required=True,
                           label='',
                           widget=forms.Textarea())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super(AbuseForm, self).__init__(*args, **kwargs)

        if (not self.request.user.is_anonymous or
                not settings.NOBOT_RECAPTCHA_PRIVATE_KEY):
            del self.fields['recaptcha']
