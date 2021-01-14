import requests

from rest_framework.reverse import reverse as drf_reverse

from django import forms
from django.conf import settings
from django.urls import NoReverseMatch

from olympia.shelves.models import Shelf


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = (
            'title',
            'endpoint',
            'criteria',
            'footer_text',
            'footer_pathname',
        )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        data = self.cleaned_data

        endpoint = data.get('endpoint')
        criteria = data.get('criteria')

        if criteria is None:
            return

        try:
            if endpoint == 'search':
                if not criteria.startswith('?') or criteria.count('?') > 1:
                    raise forms.ValidationError('Check criteria field.')
                else:
                    api = drf_reverse('addon-search', request=self.request)
                    url = api + criteria
            elif endpoint == 'collections':
                url = drf_reverse(
                    'collection-addon-list',
                    request=self.request,
                    kwargs={
                        'user_pk': settings.TASK_USER_ID,
                        'collection_slug': criteria,
                    },
                )
            else:
                return

        except NoReverseMatch:
            raise forms.ValidationError('No data found - check criteria parameters.')

        try:
            response = requests.get(url)
            if response.status_code == 404:
                raise forms.ValidationError('Check criteria - No data found')
            if response.status_code != 200:
                raise forms.ValidationError('Check criteria - %s' % response.json()[0])
            if response.json().get('count', 0) == 0:
                raise forms.ValidationError('Check criteria parameters - e.g., "type"')

        except requests.exceptions.ConnectionError:
            raise forms.ValidationError('Connection Error')
