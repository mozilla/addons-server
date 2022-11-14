import requests
from urllib import parse

from rest_framework.settings import api_settings

from django import forms
from django.conf import settings
from django.urls import NoReverseMatch, reverse

import olympia.core.logger
from olympia import amo
from olympia.amo.forms import AMOModelForm
from olympia.shelves.models import Shelf
from olympia.tags.models import Tag


log = olympia.core.logger.getLogger('z.admin.shelves')


class ShelfForm(AMOModelForm):
    # It's required in the model, but we set it to a default selectively per endpoint.
    criteria = forms.CharField(required=False)

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
            'position',
            'enabled',
        )

    def clean(self):
        base_url = settings.INTERNAL_SITE_URL

        endpoint = self.cleaned_data.get('endpoint')
        addon_type = self.cleaned_data.get('addon_type')
        criteria = self.cleaned_data.get('criteria')
        if not criteria:
            if endpoint == Shelf.Endpoints.RANDOM_TAG:
                self.cleaned_data['criteria'] = self.instance.criteria = criteria = '?'
            else:
                self.add_error(
                    'criteria', forms.ValidationError('This field is required.')
                )
                return

        if endpoint in (Shelf.Endpoints.SEARCH, Shelf.Endpoints.RANDOM_TAG):
            if not criteria.startswith('?') or criteria.count('?') > 1:
                self.add_error(
                    'criteria',
                    forms.ValidationError(
                        'Must start with a "?" and be a valid query string.'
                    ),
                )
                return
            params = dict(parse.parse_qsl(criteria.strip('?')))
            if (
                addon_type == amo.ADDON_EXTENSION
                and params.get('type') == 'statictheme'
            ):
                self.add_error(
                    None,
                    forms.ValidationError(
                        'Use "Theme (Static)" in Addon type field for type=statictheme.'
                    ),
                )
            elif (
                addon_type == amo.ADDON_STATICTHEME
                and params.get('type') != 'statictheme'
            ):
                self.add_error(
                    None,
                    forms.ValidationError(
                        'For "Theme (Static)" addon type, use type=statictheme. '
                        'For non theme addons, use "Extension" in Addon type field, '
                        'not "Theme (Static)".'
                    ),
                )

            if endpoint == Shelf.Endpoints.RANDOM_TAG:
                if 'tag' in params:
                    self.add_error(
                        'criteria',
                        forms.ValidationError(
                            'Omit `tag` param for tags shelf - a random tag will be '
                            'chosen.'
                        ),
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
                self.add_error(
                    'criteria', forms.ValidationError('Collection not found.')
                )
                return
            url = base_url + api
        else:
            return

        error_msg = None
        try:
            response = requests.get(url)
            if response.status_code == 404:
                error_msg = 'URL was a 404.'
            elif response.status_code != 200:
                error_msg = response.json()[0]
            elif response.json().get('count', 0) == 0:
                error_msg = 'No add-ons found. Check parameters - e.g., "type"'
        except requests.exceptions.ConnectionError as exc:
            log.debug('Unknown shelf validation error', exc_info=exc)
            error_msg = 'Connection Error'
        if error_msg:
            self.add_error('criteria', forms.ValidationError(error_msg))
