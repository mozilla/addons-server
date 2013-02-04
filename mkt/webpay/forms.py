from django import forms

import happyforms


class FailureForm(happyforms.Form):
    url = forms.CharField()
    attempts = forms.IntegerField()
