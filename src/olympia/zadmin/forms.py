from django import forms
from django.conf import settings
from django.forms import ModelForm
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.forms.widgets import RadioSelect
from django.utils.translation import ugettext, ugettext_lazy as _

from product_details import product_details

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.bandwagon.models import (
    Collection, FeaturedCollection, MonthlyPick)
from olympia.compat.forms import APPVER_CHOICES
from olympia.files.models import File
from olympia.lib import happyforms
from olympia.zadmin.models import SiteEvent


class DevMailerForm(happyforms.Form):
    _choices = [('eula',
                 'Developers who have set up EULAs for active add-ons'),
                ('sdk', 'Developers of active SDK add-ons'),
                ('all_extensions', 'All extension developers'),
                ('depreliminary',
                 'Developers who have addons that were preliminary reviewed'),
                ]
    recipients = forms.ChoiceField(choices=_choices, required=True)
    subject = forms.CharField(widget=forms.TextInput(attrs=dict(size='100')),
                              required=True)
    preview_only = forms.BooleanField(initial=True, required=False,
                                      label=u'Log emails instead of sending')
    message = forms.CharField(widget=forms.Textarea, required=True)


class FeaturedCollectionForm(happyforms.ModelForm):
    LOCALES = (('', u'(Default Locale)'),) + tuple(
        (i, product_details.languages[i]['native'])
        for i in settings.AMO_LANGUAGES
        if i not in ('dbl', 'dbr'))

    application = forms.ChoiceField(amo.APPS_CHOICES)
    collection = forms.CharField(widget=forms.HiddenInput)
    locale = forms.ChoiceField(choices=LOCALES, required=False)

    class Meta:
        model = FeaturedCollection
        fields = ('application', 'locale')

    def clean_collection(self):
        application = self.cleaned_data.get('application', None)
        collection = self.cleaned_data.get('collection', None)
        if not Collection.objects.filter(id=collection,
                                         application=application).exists():
            raise forms.ValidationError(
                u'Invalid collection for this application.')
        return collection

    def save(self, commit=False):
        collection = self.cleaned_data['collection']
        f = super(FeaturedCollectionForm, self).save(commit=commit)
        f.collection = Collection.objects.get(id=collection)
        f.save()
        return f


class BaseFeaturedCollectionFormSet(BaseModelFormSet):

    def __init__(self, *args, **kw):
        super(BaseFeaturedCollectionFormSet, self).__init__(*args, **kw)
        for form in self.initial_forms:
            try:
                form.initial['collection'] = (
                    FeaturedCollection.objects
                    .get(id=form.instance.id).collection.id)
            except (FeaturedCollection.DoesNotExist, Collection.DoesNotExist):
                form.initial['collection'] = None


FeaturedCollectionFormSet = modelformset_factory(
    FeaturedCollection,
    form=FeaturedCollectionForm, formset=BaseFeaturedCollectionFormSet,
    can_delete=True, extra=0)


class MonthlyPickForm(happyforms.ModelForm):
    image = forms.CharField(required=False)
    blurb = forms.CharField(max_length=200,
                            widget=forms.Textarea(attrs={'cols': 20,
                                                         'rows': 2}))

    class Meta:
        model = MonthlyPick
        widgets = {
            'addon': forms.TextInput(),
        }
        fields = ('addon', 'image', 'blurb', 'locale')


MonthlyPickFormSet = modelformset_factory(MonthlyPick, form=MonthlyPickForm,
                                          can_delete=True, extra=0)


class AddonStatusForm(ModelForm):
    class Meta:
        model = Addon
        fields = ('status',)


class FileStatusForm(ModelForm):
    class Meta:
        model = File
        fields = ('status',)

    def clean_status(self):
        changed = not self.cleaned_data['status'] == self.instance.status
        if changed and self.instance.version.deleted:
            raise forms.ValidationError(
                ugettext('Deleted versions can`t be changed.'))
        return self.cleaned_data['status']


FileFormSet = modelformset_factory(File, form=FileStatusForm,
                                   formset=BaseModelFormSet, extra=0)


class SiteEventForm(ModelForm):
    class Meta:
        model = SiteEvent
        fields = ('start', 'end', 'event_type', 'description',
                  'more_info_url')


class YesImSure(happyforms.Form):
    yes = forms.BooleanField(required=True, label="Yes, I'm sure")


class CompatForm(forms.Form):
    appver = forms.ChoiceField(choices=APPVER_CHOICES, required=False)
    type = forms.ChoiceField(choices=(('all', _('All Add-ons')),
                                      ('binary', _('Binary')),
                                      ('non-binary', _('Non-binary'))),
                             widget=RadioSelect, required=False)
    _minimum_choices = [(x, x) for x in xrange(100, -10, -10)]
    minimum = forms.TypedChoiceField(choices=_minimum_choices, coerce=int,
                                     required=False)
    _ratio_choices = [('%.1f' % (x / 10.0), '%.0f%%' % (x * 10))
                      for x in xrange(9, -1, -1)]
    ratio = forms.ChoiceField(choices=_ratio_choices, required=False)
