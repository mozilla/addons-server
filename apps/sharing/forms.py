from django import forms

from amo.helpers import absolutify
from translations.helpers import truncate


class ShareForm(forms.Form):
    """Only used for the field clean methods. Doesn't get exposed to user."""
    title = forms.CharField()
    url = forms.CharField()
    description = forms.CharField(required=False)

    def clean_url(self):
        return absolutify(self.cleaned_data.get('url'))

    def clean_description(self):
        return truncate(self.cleaned_data.get('description', ''), 250)
