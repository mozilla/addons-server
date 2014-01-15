from django import forms

import happyforms


class MonolithForm(happyforms.Form):
    key = forms.CharField(required=False)
    start = forms.DateField(required=False)
    end = forms.DateField(required=False)
