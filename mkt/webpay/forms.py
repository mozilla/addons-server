from django import forms

import happyforms

from mkt.api.forms import SluggableModelChoiceField
from mkt.webapps.models import Webapp


class PrepareForm(happyforms.Form):
    app = SluggableModelChoiceField(queryset=Webapp.objects.valid(),
                                    sluggable_to_field_name='app_slug')


class FailureForm(happyforms.Form):
    url = forms.CharField()
    attempts = forms.IntegerField()

