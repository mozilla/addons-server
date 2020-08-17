import requests

from rest_framework.reverse import reverse as drf_reverse

from django import forms
from django.conf import settings

from olympia.shelves.models import Shelf


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = ('title', 'endpoint', 'criteria',
                  'footer_text', 'footer_pathname',)

    def clean(self):
        data = self.cleaned_data

        criteria = data.get('criteria')
        endpoint = data.get('endpoint')
        baseUrl = settings.INTERNAL_SITE_URL

        if endpoint == 'search':
            api = drf_reverse('v4:addon-search')
            url = baseUrl + api + criteria
        elif endpoint == 'collections':
            api = drf_reverse('v4:collection-addon-list', kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': criteria
            })
            url = baseUrl + api
        else:
            return

        try:
            response = requests.get(url)
            if response.status_code == 404:
                raise forms.ValidationError('Check criteria - No data found')
            if response.status_code != 200:
                raise forms.ValidationError(
                    'Check criteria - %s' % response.json()[0])
            if response.json().get('count', 0) == 0:
                raise forms.ValidationError(
                    'Check criteria parameters - e.g., "type"')

        except requests.exceptions.ConnectionError:
            raise forms.ValidationError('Connection Error')
