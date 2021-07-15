import requests
from urllib import parse

from rest_framework.settings import api_settings

from django import forms
from django.conf import settings
from django.urls import NoReverseMatch, reverse

import olympia.core.logger
from olympia import amo
from olympia.shelves.models import Shelf
from olympia.tags.models import Tag


log = olympia.core.logger.getLogger('z.admin.shelves')


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = (
            'title',
            'endpoint',
            'addon_type',
            'criteria',
            'addon_count',
            'footer_text',
            'footer_pathname',
        )

    def clean(self):
        data = self.cleaned_data
        base_url = settings.INTERNAL_SITE_URL

        endpoint = data.get('endpoint')
        addon_type = data.get('addon_type')
        criteria = data.get('criteria')

        if criteria is None:
            return

        if endpoint in (Shelf.Endpoints.SEARCH, Shelf.Endpoints.TAGS):
            if not criteria.startswith('?') or criteria.count('?') > 1:
                raise forms.ValidationError('Check criteria field.')
            params = dict(parse.parse_qsl(criteria.strip('?')))
            if (
                addon_type == amo.ADDON_EXTENSION
                and params.get('type') == 'statictheme'
            ):
                raise forms.ValidationError(
                    'Use "Theme (Static)" in Addon type field for type=statictheme.'
                )
            elif (
                addon_type == amo.ADDON_STATICTHEME
                and params.get('type') != 'statictheme'
            ):
                raise forms.ValidationError(
                    'Check fields - for "Theme (Static)" addon type, use '
                    'type=statictheme. For non theme addons, use "Extension" in Addon '
                    'type field, not "Theme (Static)".'
                )
            if endpoint == Shelf.Endpoints.TAGS:
                if 'tag' in params:
                    raise forms.ValidationError(
                        'Omit `tag` param for tags shelf - a random tag will be chosen.'
                    )
                params['tag'] = Tag.objects.first().tag_text
            api = reverse(f'{api_settings.DEFAULT_VERSION}:addon-search')
            url = (
                f'{base_url}{api}?'
                f'{"&".join(f"{key}={value}" for key, value in params.items())}'
            )
        elif endpoint == Shelf.Endpoints.COLLECTIONS:
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
