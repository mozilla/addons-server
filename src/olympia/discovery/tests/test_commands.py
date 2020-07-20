# -*- coding: utf-8 -*-
import json
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings

import responses

from olympia.amo.tests import TestCase

disco_fake_data = {
    'results': [{
        'custom_heading': 'sïïïck custom heading',
        'custom_description': 'greât custom description'
    }, {
        'custom_heading': None,
        'custom_description': 'custom description is custom '
    }, {
        'custom_heading': '{start_sub_heading}{addon_name}{end_sub_heading}',
        'custom_description': ''
    }]}


primary_hero_fake_data = {
    'results': [{
        'description': 'greât primary custom description'
    }, {
        'description': 'custom primary description is custom '
    }, {
        'description': ''
    }]}


secondary_hero_fake_data = {
    'results': [{
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
                }
            }
        ]
    }, {
        'headline': None,
        'description': 'not custom description is not custom '
    }, {
        'headline': '',
        'description': None,
        'modules': [],
    }]}

expected_content = """{# L10n: editorial content for the discovery pane. #}
{% trans %}sïïïck custom heading{% endtrans %}
{# L10n: editorial content for the discovery pane. #}
{% trans %}greât custom description{% endtrans %}

{# L10n: editorial content for the discovery pane. #}
{% trans %}custom description is custom {% endtrans %}

{# L10n: editorial content for the discovery pane. #}
{% trans %}{start_sub_heading}{addon_name}{end_sub_heading}{% endtrans %}

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

"""


class TestExtractDiscoStringsCommand(TestCase):
    def test_settings(self):
        assert (
            (settings.EDITORIAL_CONTENT_FILENAME, 'jinja2')
            in settings.PUENTE['DOMAIN_METHODS']['django'])

    def test_basic(self):
        responses.add(
            responses.GET, settings.DISCOVERY_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(disco_fake_data))
        responses.add(
            responses.GET, settings.PRIMARY_HERO_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(primary_hero_fake_data))
        responses.add(
            responses.GET, settings.SECONDARY_HERO_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(secondary_hero_fake_data))

        with tempfile.NamedTemporaryFile() as file_, override_settings(
                EDITORIAL_CONTENT_FILENAME=file_.name):
            call_command('extract_content_strings')

            file_.seek(0)
            content = file_.read()
            assert content == expected_content.encode('utf-8')
