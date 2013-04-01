from django import forms

from addons.models import Category
from mkt import regions


class Featured(forms.Form):
    CHOICES = ('android', 'desktop', 'firefoxos')

    dev = forms.ChoiceField(choices=[(c, c) for c in CHOICES],
                               required=False)
    limit = forms.IntegerField(max_value=20, min_value=1, required=False)
    category = forms.ModelChoiceField(queryset=Category.objects.all(),
                                      required=False)
    region = forms.ChoiceField(choices=list(regions.REGIONS_DICT.items()),
                               required=False)

    def __init__(self, data, region=None, **kw):
        data = data.copy()
        data['region'] = region
        super(Featured, self).__init__(data, **kw)

    def as_featured(self):
        device = self.cleaned_data['dev']
        return {
            'region': regions.REGIONS_DICT.get(
                self.cleaned_data['region'], regions.WORLDWIDE),
            'mobile': device in ['android', 'firefoxos'],
            'tablet': device == 'android',
            'gaia': device == 'firefoxos',
            'cat': self.cleaned_data['category']
        }
