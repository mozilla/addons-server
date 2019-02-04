# -*- coding: utf-8 -*-
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import requests

import olympia.core.logger


log = olympia.core.logger.getLogger('z.discovery.extract_disco_strings')


class Command(BaseCommand):
    help = 'Extract editorial disco pane content that need to be translated.'

    def handle(self, *args, **options):
        results = self.fetch_strings_from_api()
        self.generate_file_from_api_results(results)

    def fetch_strings_from_api(self):
        log.info('Fetching Discovery Pane editorial content from the API.')
        response = requests.get(settings.DISCOVERY_EDITORIAL_CONTENT_API)
        if response.status_code != 200:
            raise CommandError(
                'Fetching Discovery Pane editorial content failed.')
        return json.loads(response.content)['results']

    def build_output_for_item(self, item):
        output = []
        heading = item.get('custom_heading')
        description = item.get('custom_description')
        if heading:
            output.append(self.build_output_for_single_value(heading))
        if description:
            output.append(self.build_output_for_single_value(description))
        return u''.join(output)

    def build_output_for_single_value(self, value):
        output = (u'{# L10n: editorial content for the discovery pane. #}\n'
                  u'{%% trans %%}%s{%% endtrans %%}\n' % value)
        return output

    def generate_file_from_api_results(self, results):
        log.info('Building Discovery Pane strings file.')
        content = u'\n'.join(
            self.build_output_for_item(item) for item in results)
        with open(settings.DISCOVERY_EDITORIAL_CONTENT_FILENAME, 'w') as f:
            f.write(content.encode('utf-8'))
