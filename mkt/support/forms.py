from django import forms

import happyforms


class ContactForm(happyforms.Form):
    text = forms.CharField(widget=forms.Textarea)
