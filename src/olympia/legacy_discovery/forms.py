from django import forms
from django.conf import settings

from .models import DiscoveryModule


class DiscoveryModuleForm(forms.ModelForm):
    class Meta:
        model = DiscoveryModule
        fields = ('app', 'module', 'ordering', 'locales')

    def clean_locales(self):
        # Make sure we know about the locale and remove dupes.
        data = self.cleaned_data['locales'].split()
        bad = [
            locale for locale in data if locale not in settings.AMO_LANGUAGES
        ]
        if bad:
            raise forms.ValidationError('Invalid locales: %s' % ','.join(bad))
        return ' '.join(set(data))
