from django import forms

import happyforms
from tower import ugettext_lazy as _lazy

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
