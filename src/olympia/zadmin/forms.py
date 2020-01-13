from django import forms
from django.forms import ModelForm
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.utils.translation import ugettext

import olympia.core.logger

from olympia.addons.models import Addon
from olympia.files.models import File


LOGGER_NAME = 'z.zadmin'
log = olympia.core.logger.getLogger(LOGGER_NAME)


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
