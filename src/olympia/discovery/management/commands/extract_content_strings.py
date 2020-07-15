# -*- coding: utf-8 -*-
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import requests

import olympia.core.logger


log = olympia.core.logger.getLogger('z.discovery.extract_content_strings')


class BaseAPIParser():
    def get_results_content(self):
        results = self.fetch_strings_from_api()
        log.info(f'Building "{self.l10n_comment}" strings.')
        return '\n'.join(
            self.build_output_for_item(item) for item in results)

    def fetch_strings_from_api(self):
        log.info(f'Fetching {self.l10n_comment} from the API.')
        response = requests.get(self.api)
        if response.status_code != 200:
            raise CommandError(f'Fetching {self.l10n_comment} failed.')
        return json.loads(response.content)['results']

    def _get_item(self, item, field):
        # A sub field is selected with "." e.g. addon.authors.name
        fields = field.split('.', maxsplit=1)
        sub_item = item.get(fields[0])
        if len(fields) == 1 or not sub_item:
            # Easy case, no subfields or empty/missing already.
            return sub_item
        if isinstance(sub_item, list):
            # It's a list, but we're selecting sub fields so iterate through.
            values = []
            for sub_sub in sub_item:
                value = self._get_item(sub_sub, fields[1])
                # we don't want lists of lists, so flatten along the way
                if isinstance(value, list):
                    values.extend(value)
                else:
                    values.append(value)
            return values
        else:
            # We just need to select the item from a sub field.
            return self._get_item(sub_item, fields[1])

    def build_output_for_item(self, item):
        output = []
        for field in self.fields:
            values = self._get_item(item, field)
            if not isinstance(values, list):
                values = [values]
            for value in values:
                if value:
                    output.append(self.build_output_for_single_value(value))
        return ''.join(output)

    def build_output_for_single_value(self, value):
        output = (
            '{# L10n: %s #}\n'
            '{%% trans %%}%s{%% endtrans %%}\n' % (self.l10n_comment, value))
        return output


class DiscoItemAPIParser(BaseAPIParser):
    api = settings.DISCOVERY_EDITORIAL_CONTENT_API
    l10n_comment = 'editorial content for the discovery pane.'
    fields = ('custom_heading', 'custom_description')


class PrimaryHeroShelfAPIParser(BaseAPIParser):
    api = settings.PRIMARY_HERO_EDITORIAL_CONTENT_API
    l10n_comment = 'editorial content for the primary hero shelves.'
    fields = ('description',)


class SecondaryHeroShelfAPIParser(BaseAPIParser):
    api = settings.SECONDARY_HERO_EDITORIAL_CONTENT_API
    l10n_comment = 'editorial content for the secondary hero shelves.'
    fields = ('headline', 'description', 'cta.text', 'modules.description',
              'modules.cta.text')


class Command(BaseCommand):
    help = ('Extract editorial disco pane, primary, and secondary hero shelf '
            'content that need to be translated.')

    def handle(self, *args, **options):
        disco = DiscoItemAPIParser()
        primary_hero = PrimaryHeroShelfAPIParser()
        secondary_hero = SecondaryHeroShelfAPIParser()
        results_content = (
            disco.get_results_content() + '\n' +
            primary_hero.get_results_content() +
            secondary_hero.get_results_content())
        self.generate_file_from_api_results(results_content)

    def generate_file_from_api_results(self, results_content):
        log.info('Writing Editorial content strings file.')
        with open(settings.EDITORIAL_CONTENT_FILENAME, 'wb') as f:
            f.write(results_content.encode('utf-8'))
