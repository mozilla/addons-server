from django import forms

import happyforms

from mkt.api.forms import SluggableModelChoiceField
from mkt.webapps.models import Webapp


class InstallForm(happyforms.Form):
    app = SluggableModelChoiceField(queryset=Webapp.objects.all(),
                                    sluggable_to_field_name='app_slug')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super(InstallForm, self).__init__(*args, **kwargs)

    def clean_app(self):
        app = self.cleaned_data['app']
        if app.is_premium():
            raise forms.ValidationError('Use the receipt API for paid apps.')

        return app
