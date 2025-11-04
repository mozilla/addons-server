from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import loader

import requests
from django_statsd.clients import statsd
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from olympia.amo.utils import send_mail
from olympia.core.languages import ALL_LANGUAGES


class Command(BaseCommand):
    help = (
        'Check locales completion rate for AMO projects in Pontoon and warn '
        'us by email of any falling below pre-established thresholds'
    )
    PONTOON_API = 'https://pontoon.mozilla.org/api/v2/projects/{PROJECT}/'
    PONTOON_PROJECTS = ('amo', 'amo-frontend')
    # Threshold to enable/disable locales.
    COMPLETION_THRESHOLD = 80
    # Arbitrary list of locales we always want to keep, either because they
    # receive the most traffic/affect the most users, or because they are RTL
    # and we want to keep at least one of those to ensure AMO works in RTL.
    LOCALES_TO_ALWAYS_KEEP = (
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

    def handle(self, *args, **options):
        locales_below_threshold, locales_above_threshold = (
            self.find_locales_below_and_above_threshold()
        )
        self.warn_about(
            locales_below_threshold=locales_below_threshold,
            locales_above_threshold=locales_above_threshold,
        )
        statsd.incr('amo.check_locales_completion_rate.success')

    def find_locales_below_and_above_threshold(self):
        locales_below_threshold = set()
        locales_above_threshold = set()
        locales_already_on_amo = set(settings.AMO_LANGUAGES)
        seen_locales = defaultdict(int)

        for project in self.PONTOON_PROJECTS:
            project_data = self.fetch_data(project)
            for locale_data in project_data.get('localizations', []):
                locale = self.get_locale(locale_data)
                seen_locales[locale] += 1
                completion = self.get_completion(locale_data)
                # If we see a locale below threshold, immediately add it to the
                # relevant set.
                if completion < self.COMPLETION_THRESHOLD:
                    self.stdout.write(
                        f'❌ {self.pretty_locale_name(locale)} is below threshold '
                        f'({completion}%) in {project}'
                    )
                    locales_below_threshold.add(locale)
                # If we see a language above threshold but not already enabled
                # in production, add it to the relevant set.
                elif locale not in locales_already_on_amo:
                    self.stdout.write(
                        f'✅ {self.pretty_locale_name(locale)} is above threshold '
                        f'({completion}%) in {project}'
                    )
                    locales_above_threshold.add(locale)
        # Add to locales below threshold locales we only saw in zero or one
        # project.
        # Use the ones we already have enabled in production, in case somehow
        # a locale would disappear completely from pontoon and still be enabled
        # on our side.
        for locale in locales_already_on_amo | locales_above_threshold:
            if locale != settings.LANGUAGE_CODE and seen_locales[locale] != len(
                self.PONTOON_PROJECTS
            ):
                self.stdout.write(
                    f'❌ {self.pretty_locale_name(locale)} is only in '
                    f'{seen_locales[locale]} project(s)'
                )
                locales_below_threshold.add(locale)
        # If a locale is in both sets, it shouldn't be kept in the locales
        # above threshold one, that means it's above threshold in one project
        # but below in the other.
        locales_in_both_sets = locales_above_threshold & locales_below_threshold
        for locale in locales_in_both_sets:
            self.stdout.write(f'❌ {self.pretty_locale_name(locale)} is in both sets')
        locales_above_threshold -= locales_in_both_sets
        # Now that we have used locales_below_threshold to clean up the other
        # set, we can keep the only locales that are relevant for the email,
        # which are those already on AMO.
        locales_below_threshold &= locales_already_on_amo
        return locales_below_threshold, locales_above_threshold

    def fetch_data(self, project):
        self.stdout.write(f'Calling pontoon REST api with [{project}]')
        session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=6,
                backoff_factor=1.0,
                status_forcelist=[500, 502, 503, 504],
            )
        )
        session.mount('https://', adapter)
        response = session.get(self.PONTOON_API.format(PROJECT=project), timeout=5)
        response.raise_for_status()
        return response.json()

    def get_completion(self, locale_data):
        return round(
            locale_data['approved_strings'] / locale_data['total_strings'] * 100
        )

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
                self.stdout.write(f'⚠️ {locale} should be kept but is below threshold')
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
