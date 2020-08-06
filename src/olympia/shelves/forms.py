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

        if data['shelf_type'] in ('extension', 'recommended', 'search',
                                  'theme'):
            api = drf_reverse('v4:addon-search')
            url = baseUrl + api + criteria
        elif data['shelf_type'] == 'categories':
            api = drf_reverse('v4:category-list')
            url = baseUrl + api + criteria
        elif data['shelf_type'] == 'collections':
            api = drf_reverse('v4:collection-addon-list', kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': criteria
            })
            url = baseUrl + api

        try:
            response = requests.get(url)
            if response.status_code == 404:
                raise forms.ValidationError('Check criteria - No data found')
            if response.status_code != 200:
                raise forms.ValidationError(
                    'Check criteria - %s' % response.json()[0])

            results = response.json()
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
