from datetime import datetime
import os
import re

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.forms.formsets import formset_factory

import commonware.log
import happyforms
from quieter_formset.formset import BaseFormSet
from tower import ugettext as _, ugettext_lazy as _lazy, ungettext as ngettext

from access import acl
import amo
import captcha.fields
from amo.fields import ColorField
from amo.urlresolvers import reverse
from amo.utils import slug_validator, slugify, sorted_groupby, remove_icons
from addons.models import (Addon, AddonCategory, AddonUser, BlacklistedSlug,
                           Category, Persona)
from addons.utils import reverse_name_lookup
from addons.widgets import IconWidgetRenderer, CategoriesSelectMultiple
from applications.models import Application
from devhub import tasks as devhub_tasks
from tags.models import Tag
from translations.fields import TransField, TransTextarea
from translations.forms import TranslationFormMixin
from translations.models import Translation
from translations.widgets import TranslationTextInput
from versions.models import License, Version

log = commonware.log.getLogger('z.addons')


def clean_name(name, instance=None):
    if not instance:
        log.debug('clean_name called without an instance: %s' % name)
    if instance:
        id = reverse_name_lookup(name, instance.is_webapp())
    else:
        id = reverse_name_lookup(name)

    # If we get an id and either there's no instance or the instance.id != id.
    if id and (not instance or id != instance.id):
        raise forms.ValidationError(_('This name is already in use. Please '
                                      'choose another.'))
    return name


def clean_tags(request, tags):
    target = [slugify(t, spaces=True, lower=True) for t in tags.split(',')]
    target = set(filter(None, target))

    min_len = amo.MIN_TAG_LENGTH
    max_len = Tag._meta.get_field('tag_text').max_length
    max_tags = amo.MAX_TAGS
    total = len(target)

    blacklisted = (Tag.objects.values_list('tag_text', flat=True)
                      .filter(tag_text__in=target, blacklisted=True))
    if blacklisted:
        # L10n: {0} is a single tag or a comma-separated list of tags.
        msg = ngettext('Invalid tag: {0}', 'Invalid tags: {0}',
                       len(blacklisted)).format(', '.join(blacklisted))
        raise forms.ValidationError(msg)

    restricted = (Tag.objects.values_list('tag_text', flat=True)
                     .filter(tag_text__in=target, restricted=True))
    if not acl.action_allowed(request, 'Addons', 'Edit'):
        if restricted:
            # L10n: {0} is a single tag or a comma-separated list of tags.
            msg = ngettext('"{0}" is a reserved tag and cannot be used.',
                           '"{0}" are reserved tags and cannot be used.',
                           len(restricted)).format('", "'.join(restricted))
            raise forms.ValidationError(msg)
    else:
        # Admin's restricted tags don't count towards the limit.
        total = len(target - set(restricted))

    if total > max_tags:
        num = total - max_tags
        msg = ngettext('You have {0} too many tags.',
                       'You have {0} too many tags.', num).format(num)
        raise forms.ValidationError(msg)

    if any(t for t in target if len(t) > max_len):
        raise forms.ValidationError(_('All tags must be %s characters '
                'or less after invalid characters are removed.' % max_len))

    if any(t for t in target if len(t) < min_len):
        msg = ngettext("All tags must be at least {0} character.",
                       "All tags must be at least {0} characters.",
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


class AddonFormBasic(AddonFormBase):
    name = TransField(max_length=50)
    slug = forms.CharField(max_length=30)
    summary = TransField(widget=TransTextarea(attrs={'rows': 4}),
                         max_length=250)
    tags = forms.CharField(required=False)

    class Meta:
        model = Addon
        fields = ('name', 'slug', 'summary', 'tags')

    def __init__(self, *args, **kw):
        # Force the form to use app_slug if this is a webapp. We want to keep
        # this under "slug" so all the js continues to work.
        if kw['instance'].is_webapp():
            kw.setdefault('initial', {})['slug'] = kw['instance'].app_slug

        super(AddonFormBasic, self).__init__(*args, **kw)

        # Theme summary optional.
        if kw['instance'].is_persona():
            self.fields['summary'].required = False

        self.fields['tags'].initial = ', '.join(self.get_tags(self.instance))
        # Do not simply append validators, as validators will persist between
        # instances.
        validate_name = lambda x: clean_name(x, self.instance)
        name_validators = list(self.fields['name'].validators)
        name_validators.append(validate_name)
        self.fields['name'].validators = name_validators

    def get_tags(self, addon):
        if acl.action_allowed(self.request, 'Addons', 'Edit'):
            return [t.tag_text for t in addon.tags.all()]
        else:
            return [t.tag_text for t in addon.tags.filter(restricted=False)]

    def save(self, addon, commit=False):
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

    def _post_clean(self):
        if self.instance.is_webapp():
            # Switch slug to app_slug in cleaned_data and self._meta.fields so
            # we can update the app_slug field for webapps.
            try:
                self._meta.fields = list(self._meta.fields)
                slug_idx = self._meta.fields.index('slug')
                data = self.cleaned_data
                if 'slug' in data:
                    data['app_slug'] = data.pop('slug')
                self._meta.fields[slug_idx] = 'app_slug'
                super(AddonFormBasic, self)._post_clean()
            finally:
                self._meta.fields[slug_idx] = 'slug'
        else:
            super(AddonFormBasic, self)._post_clean()

    def clean_tags(self):
        return clean_tags(self.request, self.cleaned_data['tags'])

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


class AppFormBasic(AddonFormBasic):
    """Form to override name length for apps."""
    name = TransField(max_length=128)


class ApplicationChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.id


class CategoryForm(forms.Form):
    application = ApplicationChoiceField(Application.objects.all(),
                                         widget=forms.HiddenInput,
                                         required=False)
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(), widget=CategoriesSelectMultiple)

    def save(self, addon):
        application = self.cleaned_data['application']
        categories_new = self.cleaned_data['categories']
        categories_old = [cats for app, cats in addon.app_categories if
                          (app and application and app.id == application.id) or
                          (not app and not application)]
        if categories_old:
            categories_old = categories_old[0]

        # Add new categories.
        for c in set(categories_new) - set(categories_old):
            AddonCategory(addon=addon, category=c).save()

        # Remove old categories.
        for c in set(categories_old) - set(categories_new):
            AddonCategory.objects.filter(addon=addon, category=c).delete()

    def clean_categories(self):
        categories = self.cleaned_data['categories']
        total = categories.count()
        max_cat = amo.MAX_CATEGORIES

        if getattr(self, 'disabled', False) and total:
            if categories[0].type == amo.ADDON_WEBAPP:
                raise forms.ValidationError(_('Categories cannot be changed '
                    'while your app is featured for this application.'))
            else:
                raise forms.ValidationError(_('Categories cannot be changed '
                    'while your add-on is featured for this application.'))
        if total > max_cat:
            # L10n: {0} is the number of categories.
            raise forms.ValidationError(ngettext(
                'You can have only {0} category.',
                'You can have only {0} categories.',
                max_cat).format(max_cat))

        has_misc = filter(lambda x: x.misc, categories)
        if has_misc and total > 1:
            raise forms.ValidationError(
                _('The miscellaneous category cannot be combined with '
                  'additional categories.'))

        return categories


class BaseCategoryFormSet(BaseFormSet):

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        self.request = kw.pop('request', None)
        super(BaseCategoryFormSet, self).__init__(*args, **kw)
        self.initial = []
        if self.addon.type == amo.ADDON_WEBAPP:
            apps = [None]
        else:
            apps = sorted(self.addon.compatible_apps.keys(),
                          key=lambda x: x.id)

        # Drop any apps that don't have appropriate categories.
        qs = Category.objects.filter(type=self.addon.type)
        if self.addon.type != amo.ADDON_WEBAPP:
            qs = qs.filter(application__in=[a.id for a in apps])
        app_cats = dict((k, list(v)) for k, v in
                        sorted_groupby(qs, 'application_id'))
        for app in list(apps):
            if app and not app_cats.get(app.id):
                apps.remove(app)
        if not app_cats:
            apps = []

        for app in apps:
            cats = dict(self.addon.app_categories).get(app, [])
            self.initial.append({'categories': [c.id for c in cats]})

        # Reconstruct the forms according to the initial data.
        self._construct_forms()

        for app, form in zip(apps, self.forms):
            key = app.id if app else None
            form.request = self.request
            form.initial['application'] = key
            form.app = app
            cats = sorted(app_cats[key], key=lambda x: x.name)
            form.fields['categories'].choices = [(c.id, c.name) for c in cats]

            # If this add-on is featured for this application, category
            # changes are forbidden.
            if not acl.action_allowed(self.request, 'Addons', 'Edit'):
                form.disabled = (app and self.addon.is_featured(app))

    def save(self):
        for f in self.forms:
            f.save(self.addon)


CategoryFormSet = formset_factory(form=CategoryForm,
                                  formset=BaseCategoryFormSet, extra=0)


def icons():
    """
    Generates a list of tuples for the default icons for add-ons,
    in the format (psuedo-mime-type, description).
    """
    icons = [('image/jpeg', 'jpeg'), ('image/png', 'png'), ('', 'default')]
    dirs, files = storage.listdir(settings.ADDON_ICONS_DEFAULT_PATH)
    for fname in files:
        if '32' in fname and not 'default' in fname:
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
            devhub_tasks.resize_icon.delay(upload_path, destination,
                                           amo.ADDON_ICON_SIZES,
                                           set_modified_on=[addon])

        return super(AddonFormMedia, self).save(commit)


class AddonFormDetails(AddonFormBase):
    default_locale = forms.TypedChoiceField(choices=Addon.LOCALES)

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
                raise forms.ValidationError(
                    _('Before changing your default locale you must have a '
                      'name, summary, and description in that locale. '
                      'You are missing %s.') % ', '.join(map(repr, missing)))
        return data


def get_satisfaction(url):
    """
    If there's a GetSatisfaction URL entered, we'll extract the product
    and company name..
    """
    gs_regex = "getsatisfaction\.com/(\w*)(?:/products/(\w*))?"
    match = re.search(gs_regex, url)
    if match:
        return match.groups()
    return None, None


class AddonFormSupport(AddonFormBase):
    support_url = TransField.adapt(forms.URLField)(required=False,
                                                   verify_exists=False)
    support_email = TransField.adapt(forms.EmailField)(required=False)

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')

    def __init__(self, *args, **kw):
        super(AddonFormSupport, self).__init__(*args, **kw)
        if self.instance.is_premium():
            self.fields['support_email'].required = True

    def save(self, addon, commit=True):
        instance = self.instance
        url = instance.support_url.localized_string
        (instance.get_satisfaction_company,
         instance.get_satisfaction_product) = get_satisfaction(url)
        return super(AddonFormSupport, self).save(commit)


class AddonFormTechnical(AddonFormBase):
    developer_comments = TransField(widget=TransTextarea, required=False)

    class Meta:
        model = Addon
        fields = ('developer_comments', 'view_source', 'site_specific',
                  'external_software', 'auto_repackage', 'public_stats')


class AddonForm(happyforms.ModelForm):
    name = forms.CharField(widget=TranslationTextInput,)
    homepage = forms.CharField(widget=TranslationTextInput, required=False)
    eula = forms.CharField(widget=TranslationTextInput,)
    description = forms.CharField(widget=TranslationTextInput,)
    developer_comments = forms.CharField(widget=TranslationTextInput,)
    privacy_policy = forms.CharField(widget=TranslationTextInput,)
    the_future = forms.CharField(widget=TranslationTextInput,)
    the_reason = forms.CharField(widget=TranslationTextInput,)
    support_email = forms.CharField(widget=TranslationTextInput,)

    class Meta:
        model = Addon
        fields = ('name', 'homepage', 'default_locale', 'support_email',
                  'support_url', 'description', 'summary',
                  'developer_comments', 'eula', 'privacy_policy', 'the_reason',
                  'the_future', 'view_source', 'prerelease', 'site_specific',
                  'get_satisfaction_company', 'get_satisfaction_product',)

        exclude = ('status', )

    def clean_name(self):
        name = self.cleaned_data['name']
        return clean_name(name)

    def save(self):
        desc = self.data.get('description')
        if desc and desc != unicode(self.instance.description):
            amo.log(amo.LOG.EDIT_DESCRIPTIONS, self.instance)
        if self.changed_data:
            amo.log(amo.LOG.EDIT_PROPERTIES, self.instance)

        super(AddonForm, self).save()


class AbuseForm(happyforms.Form):
    recaptcha = captcha.fields.ReCaptchaField(label='')
    text = forms.CharField(required=True,
                           label='',
                           widget=forms.Textarea())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super(AbuseForm, self).__init__(*args, **kwargs)

        if (not self.request.user.is_anonymous() or
            not settings.RECAPTCHA_PRIVATE_KEY):
            del self.fields['recaptcha']


class NewPersonaForm(AddonFormBase):
    name = forms.CharField(max_length=50)
    category = forms.ModelChoiceField(queryset=Category.objects.all(),
                                      widget=forms.widgets.RadioSelect)
    summary = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}),
                              max_length=250, required=False)
    tags = forms.CharField(required=False)

    license = forms.TypedChoiceField(choices=amo.PERSONA_LICENSES_IDS,
        coerce=int, empty_value=None, widget=forms.HiddenInput,
        error_messages={'required': _lazy(u'A license must be selected.')})
    header = forms.FileField(required=False)
    header_hash = forms.CharField(widget=forms.HiddenInput)
    footer = forms.FileField(required=False)
    footer_hash = forms.CharField(widget=forms.HiddenInput)
    accentcolor = ColorField(required=False)
    textcolor = ColorField(required=False)
    agreed = forms.BooleanField()
    # This lets us POST the data URIs of the unsaved previews so we can still
    # show them if there were form errors. It's really clever.
    unsaved_data = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Addon
        fields = ('name', 'summary', 'tags')

    def __init__(self, *args, **kwargs):
        super(NewPersonaForm, self).__init__(*args, **kwargs)
        cats = Category.objects.filter(type=amo.ADDON_PERSONA, weight__gte=0)
        cats = sorted(cats, key=lambda x: x.name)
        self.fields['category'].choices = [(c.id, c.name) for c in cats]

        for field in ('header', 'footer'):
            self.fields[field].widget.attrs = {
                'data-upload-url': reverse('devhub.personas.upload_persona',
                                           args=['persona_%s' % field]),
                'data-allowed-types': 'image/jpeg|image/png'
            }

    def clean_name(self):
        return clean_name(self.cleaned_data['name'])

    def clean_tags(self):
        return clean_tags(self.request, self.cleaned_data['tags'])

    def save(self, commit=False):
        from addons.tasks import (create_persona_preview_image,
                                  save_persona_image)
        data = self.cleaned_data
        # TODO: Ask for slug.
        addon = Addon.objects.create(name=data['name'],
            description=data.get('summary'),
            status=amo.STATUS_PENDING, type=amo.ADDON_PERSONA)
        addon._current_version = Version.objects.create(addon=addon,
                                                        version='0')
        addon.save()

        # Save header, footer, and preview images.
        try:
            header = data['header_hash']
            footer = data['footer_hash']
            header = os.path.join(settings.TMP_PATH, 'persona_header', header)
            footer = os.path.join(settings.TMP_PATH, 'persona_footer', footer)
            dst_root = os.path.join(settings.PERSONAS_PATH, str(addon.id))

            save_persona_image.delay(src=header,
                full_dst=os.path.join(dst_root, 'header.png'))
            save_persona_image.delay(src=footer,
                full_dst=os.path.join(dst_root, 'footer.png'))
            create_persona_preview_image.delay(src=header,
                full_dst=os.path.join(dst_root, 'preview.png'),
                set_modified_on=[addon])
        except IOError:
            addon.delete()
            raise

        # Save user info.
        user = self.request.amo_user
        AddonUser(addon=addon, user=user).save()

        # Create Persona instance.
        p = Persona()
        p.persona_id = 0
        p.addon = addon
        p.header = 'header.png'
        p.footer = 'footer.png'
        if data['accentcolor']:
            p.accentcolor = data['accentcolor'].lstrip('#')
        if data['textcolor']:
            p.textcolor = data['textcolor'].lstrip('#')
        p.license_id = data['license']
        p.submit = datetime.now()
        p.author = user.name
        p.display_username = user.username
        p.save()

        # Save tags.
        for t in data['tags']:
            Tag(tag_text=t).save_tag(addon)

        # Save categories.
        AddonCategory(addon=addon, category=data['category']).save()

        return addon


class ThemeLicenseForm(happyforms.Form):
    license = forms.TypedChoiceField(choices=amo.PERSONA_LICENSES_IDS,
        coerce=int, empty_value=None, widget=forms.HiddenInput,
        error_messages={'required': _lazy(u'A license must be selected.')})

    def clean_license(self):
        try:
            return License.objects.get(builtin=self.cleaned_data['license'])
        except License.DoesNotExist:
            raise forms.ValidationError(_(u'License does not exist.'))

    def save(self, addon):
        addon.persona.license = self.cleaned_data['license']
        addon.persona.save()
        return addon


class ContributionForm(happyforms.Form):
    amount = forms.DecimalField(required=True)
