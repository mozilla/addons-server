from django import forms

from .models import BlocklistApp, BlocklistPlugin


class BlocklistPluginForm(forms.ModelForm):
    class Meta:
        model = BlocklistPlugin

    def clean(self):
        severity = self.cleaned_data.get('severity')
        vulnerability = self.cleaned_data.get('vulnerability_status')

        if severity and vulnerability:
            raise forms.ValidationError('Vulnerability status must be blank if'
                                        'Severity is non zero')

        return self.cleaned_data


class BlocklistAppForm(forms.ModelForm):
    class Meta:
        model = BlocklistApp

    def clean(self):
        blthings = [self.cleaned_data.get('blitem'),
                    self.cleaned_data.get('blplugin')]

        if all(blthings) or not any(blthings):
            raise forms.ValidationError('One and only one of BlocklistPlugin'
                                        'and BlocklistItem must be set.')

        return self.cleaned_data
