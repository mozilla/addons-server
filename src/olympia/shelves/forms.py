import requests

from rest_framework.settings import api_settings

from django import forms
from django.conf import settings
from django.urls import NoReverseMatch

import olympia.core.logger
from olympia.amo.urlresolvers import reverse
from olympia.shelves.models import Shelf


log = olympia.core.logger.getLogger('z.admin.shelves')


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

    def clean(self):
        data = self.cleaned_data
        base_url = settings.INTERNAL_SITE_URL

        endpoint = data.get('endpoint')
        criteria = data.get('criteria')

        if criteria is None:
            return

        if endpoint in ('search', 'search-themes'):
            if not criteria.startswith('?') or criteria.count('?') > 1:
                raise forms.ValidationError('Check criteria field.')
            params = criteria[1:].split('&')
            if endpoint == 'search' and 'type=statictheme' in params:
                raise forms.ValidationError(
                    'Use "search-themes" endpoint for type=statictheme.'
                )
            elif endpoint == 'search-themes' and 'type=statictheme' not in params:
                raise forms.ValidationError(
                    'Don`t use "search-themes" endpoint for non themes. '
                    'Use "search".'
                )
            api = reverse(f'{api_settings.DEFAULT_VERSION}:addon-search')
            url = base_url + api + criteria
        elif endpoint == 'collections':
            try:
                api = reverse(
                    f'{api_settings.DEFAULT_VERSION}:collection-addon-list',
                    kwargs={
                        'user_pk': settings.TASK_USER_ID,
                        'collection_slug': criteria,
                    },
                )
            except NoReverseMatch:
                raise forms.ValidationError(
                    'Collection not found - check criteria parameters.'
                )
            url = base_url + api
        else:
            return

        try:
            response = requests.get(url)
            if response.status_code == 404:
                raise forms.ValidationError('URL was a 404. Check criteria')
            if response.status_code != 200:
                raise forms.ValidationError('Check criteria - %s' % response.json()[0])
            if response.json().get('count', 0) == 0:
                raise forms.ValidationError(
                    'No add-ons found. Check criteria parameters - e.g., "type"'
                )

        except requests.exceptions.ConnectionError as exc:
            log.debug('Unknown shelf validation error', exc_info=exc)
            raise forms.ValidationError('Connection Error')
