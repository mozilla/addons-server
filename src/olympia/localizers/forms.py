from django import forms


class CategoryForm(forms.Form):
    id = forms.IntegerField(widget=forms.HiddenInput)
    name = forms.CharField(required=False,
                           widget=forms.TextInput(attrs={'size': 60}))


CategoryFormSet = forms.formsets.formset_factory(CategoryForm, extra=0)
