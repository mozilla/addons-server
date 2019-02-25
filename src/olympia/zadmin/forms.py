from django import forms
from django.conf import settings
from django.forms import ModelForm
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.utils.translation import ugettext

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon
from olympia.bandwagon.models import (
    Collection, FeaturedCollection, MonthlyPick)
from olympia.core.languages import LANGUAGE_MAPPING
from olympia.files.models import File


LOGGER_NAME = 'z.zadmin'
log = olympia.core.logger.getLogger(LOGGER_NAME)


class FeaturedCollectionForm(forms.ModelForm):
    LOCALES = (('', u'(Default Locale)'),) + tuple(
        (idx, LANGUAGE_MAPPING[idx]['native'])
        for idx in settings.LANGUAGE_MAPPING)

    application = forms.ChoiceField(choices=amo.APPS_CHOICES)
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


class MonthlyPickForm(forms.ModelForm):
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
