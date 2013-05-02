from django import forms

import happyforms

from mkt.api.forms import SluggableModelChoiceField
from mkt.webapps.models import Webapp
from mkt.webpay.models import ProductIcon


class PrepareForm(happyforms.Form):
    app = SluggableModelChoiceField(queryset=Webapp.objects.valid(),
                                    sluggable_to_field_name='app_slug')


class FailureForm(happyforms.Form):
    url = forms.CharField()
    attempts = forms.IntegerField()


class ProductIconForm(happyforms.ModelForm):

    class Meta:
        model = ProductIcon
        exclude = ('format',)
