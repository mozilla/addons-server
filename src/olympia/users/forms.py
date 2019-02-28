import os

from django import forms


class DeniedNameAddForm(forms.Form):
    """Form for adding denied names in bulk fashion."""
    names = forms.CharField(widget=forms.Textarea(
        attrs={'cols': 40, 'rows': 16}))

    def clean_names(self):
        names = os.linesep.join([
            s.strip() for s in self.cleaned_data['names'].splitlines()
            if s.strip()
        ])
        return names
