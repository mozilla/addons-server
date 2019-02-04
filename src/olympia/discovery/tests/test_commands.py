# -*- coding: utf-8 -*-
import json
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings

import responses

from olympia.amo.tests import TestCase

fake_data = {
    u'results': [{
        u'custom_heading': u'sïïïck custom heading',
        u'custom_description': u'greât custom description'
    }, {
        u'custom_heading': None,
        u'custom_description': u'custom description is custom '
    }, {
        u'custom_heading': u'{start_sub_heading}{addon_name}{end_sub_heading}',
        u'custom_description': ''
    }]}

expected_content = """{# L10n: editorial content for the discovery pane. #}
{% trans %}sïïïck custom heading{% endtrans %}
{# L10n: editorial content for the discovery pane. #}
{% trans %}greât custom description{% endtrans %}

{# L10n: editorial content for the discovery pane. #}
{% trans %}custom description is custom {% endtrans %}

{# L10n: editorial content for the discovery pane. #}
{% trans %}{start_sub_heading}{addon_name}{end_sub_heading}{% endtrans %}
"""


class TestExtractDiscoStringsCommand(TestCase):
    def test_settings(self):
        assert (
            (settings.DISCOVERY_EDITORIAL_CONTENT_FILENAME, 'jinja2')
            in settings.PUENTE['DOMAIN_METHODS']['django'])

    @responses.activate
    def test_basic(self):
        responses.add(
            responses.GET, settings.DISCOVERY_EDITORIAL_CONTENT_API,
            content_type='application/json',
            body=json.dumps(fake_data))

        with tempfile.NamedTemporaryFile() as file_, override_settings(
                DISCOVERY_EDITORIAL_CONTENT_FILENAME=file_.name):
            call_command('extract_disco_strings')

            file_.seek(0)
            content = file_.read()
            assert content == expected_content
