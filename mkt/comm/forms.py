from django import forms

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

from mkt.api.forms import SluggableModelChoiceField
from mkt.constants import comm
from mkt.webapps.models import Webapp


class AppSlugForm(happyforms.Form):
    app = SluggableModelChoiceField(queryset=Webapp.objects.all(),
                                    sluggable_to_field_name='app_slug')


class CreateCommNoteForm(happyforms.Form):
    body = forms.CharField()
    note_type = forms.TypedChoiceField(
        coerce=int, choices=[(x, x) for x in comm.NOTE_TYPES],
        error_messages={'invalid_choice': _lazy(u'Invalid note type.')})


class CreateCommThreadForm(happyforms.Form):
    app = SluggableModelChoiceField(queryset=Webapp.objects.all(),
                                    sluggable_to_field_name='app_slug')
    version = forms.CharField()
    note_type = forms.TypedChoiceField(
        empty_value=comm.NO_ACTION,
        choices=[(note, note) for note in comm.NOTE_TYPES], coerce=int,
        error_messages={'invalid_choice': _lazy('Invalid note type.')})
    body = forms.CharField(
        error_messages={'required': _lazy('Note body is empty.')})

    def clean_version(self):
        version_num = self.cleaned_data['version']
        versions = self.cleaned_data['app'].versions.filter(
            version=version_num).order_by('-created')
        if versions.exists():
            return versions[0]
        raise forms.ValidationError(
            _('Version %s does not exist' % version_num))
