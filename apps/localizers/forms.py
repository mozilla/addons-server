from django import forms

from translations.widgets import TranslationTextInput


class CategoryForm(forms.Form):
    id = forms.IntegerField(widget=forms.HiddenInput)
    name = forms.CharField(required=False,
                           widget=TranslationTextInput(attrs={'size': 60}))


CategoryFormSet = forms.formsets.formset_factory(CategoryForm, extra=0)
