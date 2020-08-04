import requests

from rest_framework.reverse import reverse as drf_reverse

from django import forms
from django.conf import settings

from olympia.shelves.models import Shelf


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = ('title', 'shelf_type', 'criteria',
                  'footer_text', 'footer_pathname',)

    def clean(self):
        data = self.cleaned_data
        criteria = data['criteria']
        baseUrl = settings.INTERNAL_SITE_URL

        if data['shelf_type'] in ('extension', 'search', 'theme'):
            api = drf_reverse('v4:addon-search')
        elif data['shelf_type'] == 'categories':
            api = drf_reverse('v4:category-list')
        elif data['shelf_type'] == 'collections':
            api = drf_reverse('v4:collection-list')
        elif data['shelf_type'] == 'recommendations':
            api = drf_reverse('v4:addon-recommendations')

        url = baseUrl + api + criteria

        try:
            response = requests.get(url)
            results = response.json()

            if response.status_code == 404:
                raise forms.ValidationError('Check criteria - No data found')
            if response.status_code != 200:
                raise forms.ValidationError(
                    'Check criteria - %s' % results[0])

            # Value of results is either dict or list depending on the endpoint
            if 'count' in results:
                if results.get('count', 0) == 0:
                    raise forms.ValidationError(
                        'Check criteria parameters - e.g., "type"')
            else:
                if len(results) == 0:
                    raise forms.ValidationError(
                        'Check criteria - No data found')
        except requests.exceptions.ConnectionError:
            raise forms.ValidationError('Connection Error')
