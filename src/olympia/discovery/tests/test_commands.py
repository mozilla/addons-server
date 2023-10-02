import json
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings

import responses

from olympia.amo.tests import TestCase


disco_fake_data = {
    'results': [
        {'custom_description': 'greât custom description'},
        {'custom_description': 'custom description is custom '},
        {'custom_description': ''},
    ]
}


primary_hero_fake_data = {
    'results': [
        {'description': 'greât primary custom description'},
        {'description': 'custom primary description is custom '},
        {'description': ''},
    ]
}


secondary_hero_fake_data = {
    'results': [
        {
            'headline': 'sïïïck headline',
            'description': 'greât description',
            'cta': {
                'text': 'link to somewhere greât',
                'url': 'https://great.place/',
            },
            'modules': [
                {
                    'description': 'module description',
                },
                {
                    'description': None,
                    'cta': {
                        'text': 'CALL TO ACTION',
                        'url': None,
                    },
                },
            ],
        },
        {'headline': None, 'description': 'not custom description is not custom '},
        {
            'headline': '',
            'description': None,
            'modules': [],
        },
    ]
}

shelves_fake_data = {
    'results': [
        {'title': 'greât shelf description', 'footer_text': 'fóóter text'},
        {'title': 'custom shelf is custom ', 'footer_text': None},
        {'title': None, 'footer_text': 'fóóter text? '},
        {'title': ''},
    ]
}

expected_content = """{# L10n: editorial content for the discovery pane. #}
{% trans %}greât custom description{% endtrans %}

{# L10n: editorial content for the discovery pane. #}
{% trans %}custom description is custom {% endtrans %}


{# L10n: editorial content for the primary hero shelves. #}
{% trans %}greât primary custom description{% endtrans %}

{# L10n: editorial content for the primary hero shelves. #}
{% trans %}custom primary description is custom {% endtrans %}


{# L10n: editorial content for the secondary hero shelves. #}
{% trans %}sïïïck headline{% endtrans %}
{# L10n: editorial content for the secondary hero shelves. #}
{% trans %}greât description{% endtrans %}
{# L10n: editorial content for the secondary hero shelves. #}
{% trans %}link to somewhere greât{% endtrans %}
{# L10n: editorial content for the secondary hero shelves. #}
{% trans %}module description{% endtrans %}
{# L10n: editorial content for the secondary hero shelves. #}
{% trans %}CALL TO ACTION{% endtrans %}

{# L10n: editorial content for the secondary hero shelves. #}
{% trans %}not custom description is not custom {% endtrans %}


{# L10n: editorial content for the homepage shelves. #}
{% trans %}greât shelf description{% endtrans %}
{# L10n: editorial content for the homepage shelves. #}
{% trans %}fóóter text{% endtrans %}

{# L10n: editorial content for the homepage shelves. #}
{% trans %}custom shelf is custom {% endtrans %}

{# L10n: editorial content for the homepage shelves. #}
{% trans %}fóóter text? {% endtrans %}

"""


class TestExtractDiscoStringsCommand(TestCase):
    def test_basic(self):
        responses.add(
            responses.GET,
            settings.DISCOVERY_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(disco_fake_data),
        )
        responses.add(
            responses.GET,
            settings.PRIMARY_HERO_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(primary_hero_fake_data),
        )
        responses.add(
            responses.GET,
            settings.SECONDARY_HERO_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(secondary_hero_fake_data),
        )
        responses.add(
            responses.GET,
            settings.HOMEPAGE_SHELVES_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(shelves_fake_data),
        )

        with tempfile.NamedTemporaryFile() as file_, override_settings(
            EDITORIAL_CONTENT_FILENAME=file_.name
        ):
            call_command('extract_content_strings')

            file_.seek(0)
            content = file_.read()
            assert content == expected_content.encode('utf-8')
