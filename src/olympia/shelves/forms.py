import requests

from rest_framework.reverse import reverse as drf_reverse

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from olympia.shelves.models import Shelf


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = '__all__'

    def clean_criteria(self):
        data = self.cleaned_data
        criteria = data['criteria']
        if (data['shelf_type'] == 'extension' or
                data['shelf_type'] == 'theme' or
                data['shelf_type'] == 'search'):
            url = "https://addons.mozilla.org" + \
                drf_reverse('v4:addon-search') + criteria
        elif data['shelf_type'] == 'categories':
            url = "https://addons.mozilla.org/api/v4/addons/categories/" + \
                criteria
        elif data['shelf_type'] == 'collections':
            url = "https://addons.mozilla.org/api/v4/accounts/account/" + \
                criteria
        elif data['shelf_type'] == 'recommended':
            url = "https://addons.mozilla.org/" + \
                "api/v4/addons/recommendations/" + criteria

        response = requests.get(url)
        results = response.json()

        if response.status_code == 404:
            raise ValidationError(
                _("Check criteria field: 404 Not Found"),
                params={'criteria': criteria},)
        if response.status_code == 400:
            raise ValidationError(
                _("Check criteria field: %s" % results[0]),
                params={'criteria': criteria},)
        if response.status_code == 200 and 'results' in results:
            if len(results['results']) == 0:
                raise ValidationError(
                    _("Check parameters in criteria: e.g., 'type'"),
                    params={'criteria': criteria},)
        return criteria
