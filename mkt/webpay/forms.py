from django import forms

import happyforms

from mkt.webpay.models import ProductIcon


class FailureForm(happyforms.Form):
    url = forms.CharField()
    attempts = forms.IntegerField()


class ProductIconForm(happyforms.ModelForm):

    class Meta:
        model = ProductIcon
        exclude = ('format',)
