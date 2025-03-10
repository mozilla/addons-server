import re

import hashlib
import requests
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template import loader

from olympia.amo.utils import send_mail
from olympia.core.languages import ALL_LANGUAGES


class Command(BaseCommand):
    help = (
        'Check locales completion rate for AMO projects in Pontoon and warn '
        'us by email of any falling below pre-established thresholds'
    )
    PONTOON_API = 'https://pontoon.mozilla.org/graphql'
    PONTOON_PROJECTS = ('amo', 'amo-frontend')
    QUERY_TEMPLATE = """
        {
          project(slug: "%(project)s") {
            name,
            localizations {
              locale {
                code,
                name
              }
              totalStrings,
              approvedStrings
            }
          }
        }
    """
    # 40% completion is the first step of the project. Then we'll move it up to
    # 80% for a limited period, and eventually it will be set to 70% to account
    # for new strings being added over time.
    COMPLETION_THRESHOLD = 40
    # Arbitrary list of locales we always want to keep, either because they
    # receive the most traffic/affect the most users, or because they are RTL
    # and we want to keep at least one of those to ensure AMO works in RTL.
    LOCALES_TO_ALWAYS_KEEP = (
        'ar',
        'de',
        'en-US',
        'es-ES',
        'fr',
        'he',
        'it',
        'ja',
        'pl',
    )
    EMAIL_RECIPIENTS = ('amo-locales-notifications@mozilla.com',)
    EMAIL_SUBJECT = 'AMO locales completion rate check'
    EMAIL_TEMPLATE_PATH = 'amo/emails/locales_completion.ltxt'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Fetch data from Pontoon but do not send emails.',
        )

    def handle(self, *args, **options):
        locales_below_threshold, locales_above_threshold = (
            self.find_locales_below_and_above_threshold()
        )
        self.warn_about(
            locales_below_threshold=locales_below_threshold,
            locales_above_threshold=locales_above_threshold,
        )

    def find_locales_below_and_above_threshold(self):
        locales_below_threshold = set()
        locales_above_threshold = set()
        seen_locales = defaultdict(int)
        for project in self.PONTOON_PROJECTS:
            data = self.fetch_data(project)
            for locale_data in data.get('project', {}).get('localizations', []):
                locale = self.get_locale(locale_data)
                seen_locales[locale] += 1
                completion = self.get_completion(locale_data)
                # If we see a locale below treshold, immediately add it to the
                # relevant set.
                if completion < self.COMPLETION_THRESHOLD:
                    self.stdout.write(f'❌ {locale} is below threshold ({completion}%)')
                    locales_below_threshold.add(locale)
                # If we see a language above threshold but not already enabled
                # in production, add it to the relevant set.
                elif locale not in settings.AMO_LANGUAGES:
                    self.stdout.write(f'✅ {locale} is above threshold ({completion}%)')
                    locales_above_threshold.add(locale)
        # Add to locales below threshold locales we only saw in one project.
        # Use the ones we already have enabled in production, in case somehow
        # a locale would disappear completely from pontoon and still be enabled
        # on our side.
        for locale in settings.AMO_LANGUAGES:
            if locale != settings.LANGUAGE_CODE and seen_locales[locale] != len(
                self.PONTOON_PROJECTS
            ):
                self.stdout.write(
                    f'❌ {locale} is only in {seen_locales[locale]} project(s) !'
                )
                locales_below_threshold.add(locale)
        # Somewhat inefficient but good enough check to remove any locales that
        # both below and above threshold because of differences between the
        # projects.
        for locale in locales_above_threshold:
            if locale in locales_below_threshold:
                self.stdout.write(f'❌ {locale} is in both sets !')
                locales_above_threshold.remove(locale)
        return locales_below_threshold, locales_above_threshold

    def fetch_data(self, project):
        q = re.sub(r'\s', '', self.QUERY_TEMPLATE % {'project': project})
        self.stdout.write(f'Calling pontoon with {q}')
        response = requests.get(self.PONTOON_API, {'query': q})
        response.raise_for_status()
        data = response.json().get('data', {})
        return data

    def get_completion(self, locale_data):
        return round(locale_data['approvedStrings'] / locale_data['totalStrings'] * 100)

    def get_locale(self, locale_data):
        return locale_data['locale']['code']

    def pretty_locale_name(self, locale):
        pretty = ALL_LANGUAGES.get(locale, {}).get('english')
        if pretty:
            return f'{pretty} [{locale}]'
        return locale

    def warn_about(self, *, locales_below_threshold, locales_above_threshold):
        locales_to_keep_despite_being_below_threshold = set()
        for locale in self.LOCALES_TO_ALWAYS_KEEP:
            if locale in locales_below_threshold:
                self.stdout.write(f'⚠️ {locale} should be kept but is below threshold !')
                locales_below_threshold.remove(locale)
                locales_to_keep_despite_being_below_threshold.add(locale)
        context = {
            'COMPLETION_THRESHOLD': self.COMPLETION_THRESHOLD,
            'locales_above_threshold': '\n- '.join(
                sorted(
                    [
                        self.pretty_locale_name(locale)
                        for locale in locales_above_threshold
                    ]
                )
            ),
            'locales_below_threshold': '\n- '.join(
                sorted(
                    [
                        self.pretty_locale_name(locale)
                        for locale in locales_below_threshold
                    ]
                )
            ),
            'locales_to_keep_despite_being_below_threshold': '\n- '.join(
                sorted(
                    [
                        self.pretty_locale_name(locale)
                        for locale in locales_to_keep_despite_being_below_threshold
                    ]
                )
            ),
        }
        template = loader.get_template(self.EMAIL_TEMPLATE_PATH)
        message = template.render(context)
        send_mail(self.EMAIL_SUBJECT, message, recipient_list=self.EMAIL_RECIPIENTS)
