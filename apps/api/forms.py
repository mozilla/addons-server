from django import forms

import happyforms

from addons.models import Addon
from api.handlers import _form_error

OS = ['WINNT', 'Darwin', 'Linux']
PLATFORMS = ['x86', 'x86_64']
PRODUCTS = ['firefox']
TESTS = ['ts']

choices = lambda x: [(c, c) for c in x]


class PerformanceForm(happyforms.Form):

    addon_id = forms.IntegerField(required=False)
    os = forms.ChoiceField(choices=choices(OS))
    version = forms.CharField(max_length=255)
    platform = forms.ChoiceField(choices=choices(PLATFORMS))
    product = forms.ChoiceField(choices=choices(PRODUCTS))
    product_version = forms.CharField(max_length=255)
    average = forms.FloatField()
    test = forms.ChoiceField(choices=choices(TESTS))

    def show_error(self):
        return _form_error(self)

    def clean_addon_id(self):
        if self.data.get('addon_id'):
            try:
                # Add addon into the form data, leaving addon_id alone.
                addon = Addon.objects.get(pk=self.data['addon_id'])
                self.cleaned_data['addon'] = addon
                return addon.pk
            except Addon.DoesNotExist:
                raise forms.ValidationError('Add-on not found: %s'
                                            % self.data['addon_id'])

    @property
    def os_version(self):
        return dict([k, self.cleaned_data[k]]
                    for k in ['os', 'version', 'platform'])

    @property
    def app_version(self):
        return {'app': self.cleaned_data['product'],
                'version': self.cleaned_data['product_version']}

    @property
    def performance(self):
        return dict([k, self.cleaned_data.get(k)] for k in ['addon', 'test'])
