import os

from datetime import datetime
from urlparse import urlsplit

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.forms.formsets import BaseFormSet, formset_factory
from django.utils.translation import ugettext, ugettext_lazy as _, ungettext

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon, AddonCategory, Category, DeniedSlug, Persona)
from olympia.addons.tasks import save_theme, save_theme_reupload
from olympia.addons.widgets import CategoriesSelectMultiple, IconWidgetRenderer
from olympia.addons.utils import verify_mozilla_trademark
from olympia.amo.fields import (
    ColorField, HttpHttpsOnlyURLField, ReCaptchaField)
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import (
    remove_icons, slug_validator, slugify, sorted_groupby)
from olympia.devhub import tasks as devhub_tasks
from olympia.lib import happyforms
from olympia.tags.models import Tag
from olympia.translations import LOCALES
from olympia.translations.fields import TransField, TransTextarea
from olympia.translations.forms import TranslationFormMixin
from olympia.translations.models import Translation
from olympia.translations.utils import transfield_changed
from olympia.users.models import UserEmailField
from olympia.versions.models import Version


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


class AddonFormBase(TranslationFormMixin, happyforms.ModelForm):

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonFormBase, self).__init__(*args, **kw)

    class Meta:
        models = Addon
        fields = ('name', 'slug', 'summary', 'tags')

    def clean_slug(self):
        return clean_addon_slug(self.cleaned_data['slug'], self.instance)

    def clean_name(self):
        user = getattr(self.request, 'user', None)

        name = verify_mozilla_trademark(self.cleaned_data['name'], user)

        return name

    def clean_tags(self):
        return clean_tags(self.request, self.cleaned_data['tags'])

    def get_tags(self, addon):
        if acl.action_allowed(self.request, amo.permissions.ADDONS_EDIT):
            return list(addon.tags.values_list('tag_text', flat=True))
        else:
            return list(addon.tags.filter(restricted=False)
                        .values_list('tag_text', flat=True))


class AddonFormBasic(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}),
                         max_length=250)
    tags = forms.CharField(required=False)
    contributions = HttpHttpsOnlyURLField(required=False, max_length=255)
    is_experimental = forms.BooleanField(required=False)
    requires_payment = forms.BooleanField(required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags', 'is_experimental',
                  'requires_payment', 'contributions')

    def __init__(self, *args, **kw):
        super(AddonFormBasic, self).__init__(*args, **kw)

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
        addonform = super(AddonFormBasic, self).save(commit=False)
        addonform.save()

        return addonform


class AddonFormBasicUnlisted(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}),
                         max_length=250)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary')


class CategoryForm(forms.Form):
    application = forms.TypedChoiceField(amo.APPS_CHOICES, coerce=int,
                                         widget=forms.HiddenInput,
                                         required=True)
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(), widget=CategoriesSelectMultiple)

    def save(self, addon):
        application = self.cleaned_data.get('application')
        categories_new = [c.id for c in self.cleaned_data['categories']]
        categories_old = [
            c.id for c in
            addon.app_categories.get(amo.APP_IDS[application], [])]

        # Add new categories.
        for c_id in set(categories_new) - set(categories_old):
            AddonCategory(addon=addon, category_id=c_id).save()

        # Remove old categories.
        for c_id in set(categories_old) - set(categories_new):
            AddonCategory.objects.filter(
                addon=addon, category_id=c_id).delete()

        # Remove old, outdated categories cache on the model.
        del addon.all_categories

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

        has_misc = filter(lambda x: x.misc, categories)
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
            cats = self.addon.app_categories.get(app, [])
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
        if '32' in fname and 'default' not in fname:
            icon_name = fname.split('-')[0]
            icons.append(('icon/%s' % icon_name, icon_name))
    return icons


class AddonFormMedia(AddonFormBase):
    icon_type = forms.CharField(widget=forms.RadioSelect(
        renderer=IconWidgetRenderer, choices=[]), required=False)
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


class AddonFormDetails(AddonFormBase):
    default_locale = forms.TypedChoiceField(choices=LOCALES)
    homepage = TransField.adapt(HttpHttpsOnlyURLField)(required=False)

    class Meta:
        model = Addon
        fields = ('description', 'default_locale', 'homepage')

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
                raise forms.ValidationError(ugettext(
                    'Before changing your default locale you must have a '
                    'name, summary, and description in that locale. '
                    'You are missing %s.') % ', '.join(map(repr, missing)))
        return data


class AddonFormDetailsUnlisted(AddonFormBase):
    homepage = TransField.adapt(HttpHttpsOnlyURLField)(required=False)

    class Meta:
        model = Addon
        fields = ('description', 'homepage')


class AddonFormSupport(AddonFormBase):
    support_url = TransField.adapt(HttpHttpsOnlyURLField)(required=False)
    support_email = TransField.adapt(forms.EmailField)(required=False)

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')

    def __init__(self, *args, **kw):
        super(AddonFormSupport, self).__init__(*args, **kw)

    def save(self, addon, commit=True):
        return super(AddonFormSupport, self).save(commit)


class AddonFormTechnical(AddonFormBase):
    developer_comments = TransField(widget=TransTextarea, required=False)

    class Meta:
        model = Addon
        fields = ('developer_comments', 'view_source', 'external_software',
                  'auto_repackage', 'public_stats')


class AddonFormTechnicalUnlisted(AddonFormBase):
    class Meta:
        model = Addon
        fields = ()


class AbuseForm(happyforms.Form):
    recaptcha = ReCaptchaField(label='')
    text = forms.CharField(required=True,
                           label='',
                           widget=forms.Textarea())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super(AbuseForm, self).__init__(*args, **kwargs)

        if (not self.request.user.is_anonymous() or
                not settings.NOBOT_RECAPTCHA_PRIVATE_KEY):
            del self.fields['recaptcha']


class ThemeFormBase(AddonFormBase):

    def __init__(self, *args, **kwargs):
        super(ThemeFormBase, self).__init__(*args, **kwargs)
        cats = Category.objects.filter(type=amo.ADDON_PERSONA, weight__gte=0)
        cats = sorted(cats, key=lambda x: x.name)
        self.fields['category'].choices = [(c.id, c.name) for c in cats]

        for field in ('header', ):
            self.fields[field].widget.attrs = {
                'data-upload-url': reverse('devhub.personas.upload_persona',
                                           args=['persona_%s' % field]),
                'data-allowed-types': amo.SUPPORTED_IMAGE_TYPES
            }


class ThemeForm(ThemeFormBase):
    name = forms.CharField(max_length=50)
    slug = forms.CharField(max_length=30)
    category = forms.ModelChoiceField(queryset=Category.objects.all(),
                                      widget=forms.widgets.RadioSelect)
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}),
                                  max_length=500, required=False)
    tags = forms.CharField(required=False)

    license = forms.TypedChoiceField(
        choices=amo.PERSONA_LICENSES_CHOICES,
        coerce=int, empty_value=None, widget=forms.HiddenInput,
        error_messages={'required': _(u'A license must be selected.')})
    header = forms.FileField(required=False)
    header_hash = forms.CharField(widget=forms.HiddenInput)
    # Native color picker doesn't allow real time tracking of user input
    # and empty values, thus force the JavaScript color picker for now.
    # See bugs 1005206 and 1003575.
    accentcolor = ColorField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'color-picker'}),
    )
    textcolor = ColorField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'color-picker'}),
    )
    agreed = forms.BooleanField()
    # This lets us POST the data URIs of the unsaved previews so we can still
    # show them if there were form errors. It's really clever.
    unsaved_data = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'description', 'tags')

    def save(self, commit=False):
        data = self.cleaned_data
        addon = Addon.objects.create(
            slug=data.get('slug'),
            status=amo.STATUS_PENDING, type=amo.ADDON_PERSONA)
        addon.name = {'en-US': data['name']}
        if data.get('description'):
            addon.description = data['description']
        addon._current_version = Version.objects.create(addon=addon,
                                                        version='0')
        addon.save()

        # Create Persona instance.
        p = Persona()
        p.persona_id = 0
        p.addon = addon
        p.header = 'header.png'
        if data['accentcolor']:
            p.accentcolor = data['accentcolor'].lstrip('#')
        if data['textcolor']:
            p.textcolor = data['textcolor'].lstrip('#')
        p.license = data['license']
        p.submit = datetime.now()
        user = self.request.user
        p.author = user.username
        p.display_username = user.name
        p.save()

        # Save header and preview images.
        save_theme.delay(data['header_hash'], addon.pk)

        # Save user info.
        addon.addonuser_set.create(user=user, role=amo.AUTHOR_ROLE_OWNER)

        # Save tags.
        for t in data['tags']:
            Tag(tag_text=t).save_tag(addon)

        # Save categories.
        AddonCategory(addon=addon, category=data['category']).save()

        return addon


class EditThemeForm(AddonFormBase):
    name = TransField(max_length=50, label=_('Give Your Theme a Name.'))
    slug = forms.CharField(max_length=30)
    category = forms.ModelChoiceField(queryset=Category.objects.all(),
                                      widget=forms.widgets.RadioSelect)
    description = TransField(
        widget=TransTextarea(attrs={'rows': 4}),
        max_length=500, required=False, label=_('Describe your Theme.'))
    tags = forms.CharField(required=False)
    accentcolor = ColorField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'color-picker'}),
    )
    textcolor = ColorField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'color-picker'}),
    )
    license = forms.TypedChoiceField(
        choices=amo.PERSONA_LICENSES_CHOICES, coerce=int, empty_value=None,
        widget=forms.HiddenInput,
        error_messages={'required': _(u'A license must be selected.')})

    # Theme re-upload.
    header = forms.FileField(required=False)
    header_hash = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'description', 'tags')

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')

        super(AddonFormBase, self).__init__(*args, **kw)

        addon = Addon.objects.get(id=self.instance.id)
        persona = addon.persona

        # Allow theme artists to localize Name and Description.
        for trans in Translation.objects.filter(id=self.initial['name']):
            self.initial['name_' + trans.locale.lower()] = trans
        for trans in Translation.objects.filter(
                id=self.initial['description']):
            self.initial['description_' + trans.locale.lower()] = trans

        self.old_tags = self.get_tags(addon)
        self.initial['tags'] = ', '.join(self.old_tags)
        if persona.accentcolor:
            self.initial['accentcolor'] = '#' + persona.accentcolor
        if persona.textcolor:
            self.initial['textcolor'] = '#' + persona.textcolor
        self.initial['license'] = persona.license

        cats = sorted(Category.objects.filter(type=amo.ADDON_PERSONA,
                                              weight__gte=0),
                      key=lambda x: x.name)
        self.fields['category'].choices = [(c.id, c.name) for c in cats]
        try:
            self.initial['category'] = addon.categories.values_list(
                'id', flat=True)[0]
        except IndexError:
            pass

        for field in ('header', ):
            self.fields[field].widget.attrs = {
                'data-upload-url': reverse('devhub.personas.reupload_persona',
                                           args=[addon.slug,
                                                 'persona_%s' % field]),
                'data-allowed-types': amo.SUPPORTED_IMAGE_TYPES
            }

    def clean_slug(self):
        return clean_addon_slug(self.cleaned_data['slug'], self.instance)

    def save(self):
        addon = self.instance
        persona = addon.persona
        data = self.cleaned_data

        # Update Persona-specific data.
        persona_data = {
            'license': int(data['license']),
            'accentcolor': data['accentcolor'].lstrip('#'),
            'textcolor': data['textcolor'].lstrip('#'),
            'author': self.request.user.username,
            'display_username': self.request.user.name
        }
        changed = False
        for k, v in persona_data.iteritems():
            if v != getattr(persona, k):
                changed = True
                setattr(persona, k, v)
        if changed:
            persona.save()

        if self.changed_data:
            ActivityLog.create(amo.LOG.EDIT_PROPERTIES, addon)
        self.instance.modified = datetime.now()

        # Update Addon-specific data.
        changed = (
            set(self.old_tags) != data['tags'] or  # Check if tags changed.
            self.initial['slug'] != data['slug'] or  # Check if slug changed.
            transfield_changed('description', self.initial, data) or
            transfield_changed('name', self.initial, data))
        if changed:
            # Only save if addon data changed.
            super(EditThemeForm, self).save()

        # Update tags.
        tags_new = data['tags']
        tags_old = [slugify(t, spaces=True) for t in self.old_tags]
        # Add new tags.
        for t in set(tags_new) - set(tags_old):
            Tag(tag_text=t).save_tag(addon)
        # Remove old tags.
        for t in set(tags_old) - set(tags_new):
            Tag(tag_text=t).remove_tag(addon)

        # Update category.
        if data['category'].id != self.initial['category']:
            addon_cat = addon.addoncategory_set.all()[0]
            addon_cat.category = data['category']
            addon_cat.save()

        # Theme reupload.
        if not addon.is_pending():
            if data['header_hash']:
                save_theme_reupload.delay(data['header_hash'], addon.pk)

        return data


class EditThemeOwnerForm(happyforms.Form):
    owner = UserEmailField()

    def __init__(self, *args, **kw):
        self.instance = kw.pop('instance')

        super(EditThemeOwnerForm, self).__init__(*args, **kw)

        addon = self.instance

        self.fields['owner'].widget.attrs['placeholder'] = _(
            "Enter a new author's email address")

        try:
            self.instance_addonuser = addon.addonuser_set.all()[0]
            self.initial['owner'] = self.instance_addonuser.user.email
        except IndexError:
            # If there was never an author before, then don't require one now.
            self.instance_addonuser = None
            self.fields['owner'].required = False

    def save(self):
        data = self.cleaned_data

        if data.get('owner'):
            changed = (not self.instance_addonuser or
                       self.instance_addonuser != data['owner'])
            if changed:
                # Update Persona-specific data.
                persona = self.instance.persona
                persona.author = data['owner'].username
                persona.display_username = data['owner'].name
                persona.save()

            if not self.instance_addonuser:
                # If there previously never another owner, create one.
                self.instance.addonuser_set.create(user=data['owner'],
                                                   role=amo.AUTHOR_ROLE_OWNER)
            elif self.instance_addonuser != data['owner']:
                # If the owner has changed, update the `AddonUser` object.
                self.instance_addonuser.user = data['owner']
                self.instance_addonuser.role = amo.AUTHOR_ROLE_OWNER
                self.instance_addonuser.save()

            self.instance.modified = datetime.now()
            self.instance.save()

        return data
