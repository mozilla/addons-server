from django import forms
from django.conf import settings
from django.forms import TextInput

import happyforms
import re
import amo
from tower import ugettext as _, ungettext as ngettext

from addons.models import Addon, Category
from amo.utils import slug_validator
from tags.models import Tag
from translations.widgets import TranslationTextInput, TranslationTextarea


class AddonFormBasic(happyforms.ModelForm):
    name = forms.CharField(widget=TranslationTextInput,max_length=70)
    slug = forms.CharField(max_length=30)
    summary = forms.CharField(widget=TranslationTextarea,max_length=250)
    tags = forms.CharField()

    categories = forms.ModelMultipleChoiceField(queryset=False,
                                                widget=
                                                forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kw):
        super(AddonFormBasic, self).__init__(*args, **kw)

        #TODO(gkoberger): un-hard-code the 1

        self.fields['categories'].queryset = Category.objects.filter(
                                               application=1,
                                               type=self.instance.type)
        self.fields['tags'].initial = ", ".join([tag.tag_text for tag in
                                                 self.instance.tags.all()])

    def save(self, addon, commit=False):
        tags_new = [t.strip() for t in self.cleaned_data['tags'].split(',')]
        tags_old = [t.tag_text for t in addon.tags.all()]

        #Add new tags.
        for t in tags_new:
            Tag(tag_text=t).save_tag(addon)

        #Remove old tags.
        for t in set(tags_old) - set(tags_new):
            Tag(tag_text=t).remove_tag(addon)

        return super(AddonFormBasic, self).save()

    def clean_slug(self):
        target = self.cleaned_data['slug']

        slug_validator(target, lower=False)

        if self.cleaned_data['slug'] != self.instance.slug:
            if Addon.objects.filter(slug=target).exists():
                raise forms.ValidationError(_('This slug is already in use.'))
        return target

    def clean_categories(self):

        max_cat = amo.MAX_CATEGORY
        total = len(self.cleaned_data['categories'].all())

        if total > max_cat:
            raise forms.ValidationError(ngettext(
                                            'You can only have {0} category.',
                                            'You can only have {0} categories',
                                            max_cat).format(max_cat))
        return self.cleaned_data['categories']

    def clean_tags(self):
        target = self.cleaned_data['tags']
        max_tags = amo.MAX_TAGS
        total = len(target.split(','))

        if total > max_tags:
            raise forms.ValidationError(_('You have {0} too many tags.')
                                         .format(total - max_tags))
        return target

    class Meta:
        model = Addon
        widgets = {
            'tags': TranslationTextInput,
        }

        fields = ('name', 'summary', 'categories', 'tags', 'slug')


class AddonFormDetails(happyforms.ModelForm):

    description = forms.CharField(widget=TranslationTextarea)

    default_locale = forms.TypedChoiceField(choices=Addon.LOCALES)
    homepage = forms.URLField(widget=TranslationTextInput)

    class Meta:
        mode = Addon
        fields = ('description', 'default_locale', 'homepage')


class AddonFormSupport(happyforms.ModelForm):
    support_url = forms.URLField(widget=TranslationTextInput)
    support_email = forms.EmailField(widget=TranslationTextInput)

    get_satisfaction_company = forms.CharField(widget=TranslationTextInput,
                                required=False)
    get_satisfaction_product = forms.CharField(widget=TranslationTextInput,
                                required=False)

    def save(self, addon, commit=False):
        instance = self.instance

        match = re.search("getsatisfaction\.com/([a-zA-Z0-9_]*)" +
                                      "(?:/products/([a-zA-Z0-9_]*))?",
                                      instance.support_url.localized_string)
        if match:
            company, product = match.groups()
            self.instance.get_satisfaction_company = company
            self.instance.get_satisfaction_product = product

        return super(AddonFormSupport, self).save()

    class Meta:
        mode = Addon
        fields = ('support_email', 'support_url', 'get_satisfaction_company',
                  'get_satisfaction_product')

class AddonFormTechnical(happyforms.ModelForm):
    developer_comments = forms.CharField(widget=TranslationTextarea)
    view_source = forms.BooleanField(required=False)
    site_specific = forms.BooleanField(required=False)
    external_software = forms.BooleanField(required=False)
    binary = forms.BooleanField(required=False)

    class Meta:
        mode = Addon
        fields = ('developer_comments', 'view_source', 'site_specific',
                'external_software', 'binary')


class AddonForm(AddonFormBasic, AddonFormDetails, AddonFormSupport,
                AddonFormTechnical):
    eula = forms.CharField(widget=TranslationTextInput)
    privacy_policy = forms.CharField(widget=TranslationTextInput)
    the_future = forms.CharField(widget=TranslationTextInput)
    the_reason = forms.CharField(widget=TranslationTextInput)

    class Meta:
        model = Addon
        exclude = ('status', )
