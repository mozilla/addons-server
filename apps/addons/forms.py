import os
import re

from django import forms
from django.conf import settings
from django.forms.formsets import BaseFormSet, formset_factory

import happyforms
import path
from tower import ugettext as _, ungettext as ngettext

from access import acl
import amo
import captcha.fields
from amo.utils import slug_validator, slugify, sorted_groupby, remove_icons
from addons.models import (Addon, AddonCategory, BlacklistedSlug,
                           Category, ReverseNameLookup)
from addons.widgets import IconWidgetRenderer, CategoriesSelectMultiple
from applications.models import Application
from devhub import tasks
from tags.models import Tag
from translations.fields import TransField, TransTextarea
from translations.forms import TranslationFormMixin
from translations.models import Translation
from translations.widgets import TranslationTextInput


def clean_name(name, instance=None):
    id = ReverseNameLookup.get(name)

    # If we get an id and either there's no instance or the instance.id != id.
    if id and (not instance or id != instance.id):
        raise forms.ValidationError(_('This add-on name is already in use.  '
                                      'Please choose another.'))
    return name


class AddonFormBase(TranslationFormMixin, happyforms.ModelForm):

    def __init__(self, *args, **kw):
        self.request = kw.pop('request')
        super(AddonFormBase, self).__init__(*args, **kw)


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
        super(AddonFormBasic, self).__init__(*args, **kw)
        self.fields['tags'].initial = ', '.join(self.get_tags(self.instance))
        # Do not simply append validators, as validators will persist between
        # instances.
        validate_name = lambda x: clean_name(x, self.instance)
        name_validators = list(self.fields['name'].validators)
        name_validators.append(validate_name)
        self.fields['name'].validators = name_validators

    def get_tags(self, addon):
        if acl.action_allowed(self.request, 'Admin', 'EditAnyAddon'):
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

    def clean_tags(self):
        target = [slugify(t, spaces=True, lower=True)
                  for t in self.cleaned_data['tags'].split(',')]
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
        if not acl.action_allowed(self.request, 'Admin', 'EditAnyAddon'):
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

    def clean_slug(self):
        target = self.cleaned_data['slug']
        slug_validator(target, lower=False)

        if target != self.instance.slug:
            if Addon.objects.filter(slug=target).exists():
                raise forms.ValidationError(_('This slug is already in use.'))

            if BlacklistedSlug.blocked(target):
                raise forms.ValidationError(_('The slug cannot be: %s.'
                                              % target))
        return target


class ApplicationChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return obj.id


class CategoryForm(forms.Form):
    application = ApplicationChoiceField(Application.objects.all(),
                                         widget=forms.HiddenInput)
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.all(), widget=CategoriesSelectMultiple)

    def save(self, addon):
        categories_new = self.cleaned_data['categories']
        categories_old = [cats for app, cats in addon.app_categories
                          if app.id == self.cleaned_data['application'].id]
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
        if total > max_cat:
            raise forms.ValidationError(ngettext(
                'You can have only {0} category.',
                'You can have only {0} categories.',
                max_cat).format(max_cat))

        has_misc = filter(lambda x: x.misc, categories)
        if has_misc and total > 1:
            raise forms.ValidationError(
                _("The miscellaneous category cannot be combined with "
                  "additional categories."))

        return categories


class BaseCategoryFormSet(BaseFormSet):

    def __init__(self, *args, **kw):
        self.addon = kw.pop('addon')
        super(BaseCategoryFormSet, self).__init__(*args, **kw)
        self.initial = []
        apps = sorted(self.addon.compatible_apps.keys(), key=lambda x: x.id)

        # Drop any apps that don't have appropriate categories.
        qs = Category.objects.filter(type=self.addon.type,
                                     application__in=[a.id for a in apps])
        app_cats = dict((k, list(v))
                        for k, v in sorted_groupby(qs, 'application_id'))
        for app in list(apps):
            if not app_cats.get(app.id):
                apps.remove(app)

        for app in apps:
            cats = dict(self.addon.app_categories).get(app, [])
            self.initial.append({'categories': [c.id for c in cats]})

        # Reconstruct the forms according to the initial data.
        self._construct_forms()

        for app, form in zip(apps, self.forms):
            form.initial['application'] = app.id
            form.app = app
            cats = sorted(app_cats[app.id], key=lambda x: x.name)
            form.fields['categories'].choices = [(c.id, c.name) for c in cats]

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
    dir_list = os.listdir(settings.ADDON_ICONS_DEFAULT_PATH)
    for fname in dir_list:
        if '32' in fname and not 'default' in fname:
            icon_name = fname.split('-')[0]
            icons.append(('icon/%s' % icon_name, icon_name))
    return icons


class AddonFormMedia(AddonFormBase):
    icon_type = forms.CharField(widget=forms.RadioSelect(
            renderer=IconWidgetRenderer, choices=icons()), required=False)
    icon_upload_hash = forms.CharField(required=False)

    class Meta:
        model = Addon
        fields = ('icon_upload_hash', 'icon_type')

    def save(self, addon, commit=True):
        if self.cleaned_data['icon_upload_hash']:
            upload_hash = self.cleaned_data['icon_upload_hash']
            upload_path = path.path(settings.TMP_PATH) / 'icon' / upload_hash

            dirname = addon.get_icon_dir()
            destination = os.path.join(dirname, '%s' % addon.id)

            remove_icons(destination)
            tasks.resize_icon.delay(upload_path, destination,
                                    amo.ADDON_ICON_SIZES)

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


class AddonFormSupport(AddonFormBase):
    support_url = TransField.adapt(forms.URLField)(required=False,
                                                   verify_exists=False)
    support_email = TransField.adapt(forms.EmailField)(required=False)

    class Meta:
        model = Addon
        fields = ('support_email', 'support_url')

    def save(self, addon, commit=True):
        instance = self.instance

        # If there's a GetSatisfaction URL entered, we'll extract the product
        # and company name and save it to the DB.
        gs_regex = "getsatisfaction\.com/(\w*)(?:/products/(\w*))?"
        match = re.search(gs_regex, instance.support_url.localized_string)

        company = product = None

        if match:
            company, product = match.groups()

        instance.get_satisfaction_company = company
        instance.get_satisfaction_product = product

        return super(AddonFormSupport, self).save(commit)


class AddonFormTechnical(AddonFormBase):
    developer_comments = TransField(widget=TransTextarea, required=False)

    class Meta:
        model = Addon
        fields = ('developer_comments', 'view_source', 'site_specific',
                  'external_software', 'binary')


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
                  'the_future', 'view_source', 'prerelease', 'binary',
                  'site_specific', 'get_satisfaction_company',
                  'get_satisfaction_product',)

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
