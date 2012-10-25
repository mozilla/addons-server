from django import forms

from .models import BlocklistPlugin


class BlocklistPluginForm(forms.ModelForm):
    class Meta:
        model = BlocklistPlugin

    def clean(self):
        severity = self.cleaned_data.get('severity')
        vulnerability = self.cleaned_data.get('vulnerability_status')

        if severity and vulnerability:
            raise forms.ValidationError(
                'Vulnerability status must be blank if Severity is non zero')

        return self.cleaned_data
