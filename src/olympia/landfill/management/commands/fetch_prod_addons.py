import requests
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.transaction import atomic

from olympia import amo
from olympia.amo.tests import addon_factory, user_factory
from olympia.constants.categories import CATEGORIES
from olympia.addons.models import Addon
from olympia.users.models import UserProfile


class KeyboardInterruptError(Exception):
    pass


class Command(BaseCommand):
    """Download and save all AMO add-ons public data."""

    SEARCH_API_URL = 'https://addons.mozilla.org/api/v5/addons/search/'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max', metavar='max', type=int, help='max amount of pages to fetch.'
        )
        parser.add_argument(
            '--guid', metavar='guid', type=str, help='specific guid(s) to fetch.'
        )
        parser.add_argument(
            '--type',
            metavar='type',
            type=str,
            help='only consider this specific add-on type',
        )
        parser.add_argument(
            '--query',
            metavar='type',
            type=str,
            help='only consider add-ons matching this query',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'As a safety precaution this command only works if DEBUG=True.'
            )
        self.fetch_addon_data(options)

    def get_max_pages(self, params=None):
        response = requests.get(self.SEARCH_API_URL, params=params)
        return response.json()['page_count']

    def _get_addons_from_page(self, page, params=None):
        data = []
        print('fetching %s' % page)
        query_params = {'page': page}
        if params:
            query_params.update(params)
        response = requests.get(self.SEARCH_API_URL, params=query_params)
        print('fetched %s' % page)

        for addon in response.json()['results']:
            self._handle_addon(addon)

        return data

    def _handle_addon(self, addon_data):
        version = addon_data['current_version']
        files = version['files'] or []

        file_kw = {}

        try:
            file_kw = {
                'hash': files[0]['hash'],
                'status': amo.STATUS_CHOICES_API_LOOKUP[files[0]['status']],
                'platform': amo.PLATFORM_DICT[files[0]['platform']].id,
                'size': files[0]['size'],
                'is_webextension': files[0]['is_webextension'],
                'is_mozilla_signed_extension': (
                    files[0]['is_mozilla_signed_extension']
                ),
                'strict_compatibility': (version['is_strict_compatibility_enabled']),
            }
        except (KeyError, IndexError):
            file_kw = {}

        # TODO:
        # * license
        # * ratings
        # * previews
        # * android compat & category data

        if Addon.objects.filter(slug=addon_data['slug']).exists():
            print('Skipping %s (slug already exists)' % addon_data['slug'])
            return

        if (
            addon_data['guid']
            and Addon.objects.filter(guid=addon_data['guid']).exists()
        ):
            print('Skipping %s (guid already exists)' % addon_data['guid'])
            return

        users = []

        for user in addon_data['authors']:
            try:
                users.append(UserProfile.objects.get(username=user['name']))
            except UserProfile.DoesNotExist:
                email = 'fake-prod-data-%s@mozilla.com' % str(uuid.uuid4().hex)
                users.append(user_factory(username=user['name'], email=email))

        addon_type = amo.ADDON_SEARCH_SLUGS[addon_data['type']]

        if 'firefox' in addon_data['categories']:
            category = addon_data['categories']['firefox'][0]
        else:
            category = None

        if category not in CATEGORIES[amo.FIREFOX.id][addon_type]:
            category = None
            print('Category %s' % category, 'not found')
        else:
            category = CATEGORIES[amo.FIREFOX.id][addon_type][category]

        print('Creating add-on %s' % addon_data['slug'])

        compatibility = version['compatibility']

        if compatibility and 'firefox' in compatibility:
            version_kw = {
                'min_app_version': version['compatibility']['firefox']['min'],
                'max_app_version': version['compatibility']['firefox']['max'],
            }
        else:
            version_kw = {}

        with atomic():
            addon_factory(
                users=users,
                average_daily_users=addon_data['average_daily_users'],
                category=category,
                type=addon_type,
                guid=addon_data['guid'],
                slug=addon_data['slug'],
                name=addon_data['name'],
                summary=addon_data['summary'],
                description=addon_data['description'],
                file_kw=file_kw,
                version_kw=version_kw,
                weekly_downloads=addon_data.get('weekly_downloads', 0),
                default_locale=addon_data['default_locale'],
                tags=addon_data['tags'],
            )

    def fetch_addon_data(self, options):
        params = {
            'app': 'firefox',
            'appversion': '60.0',
        }
        if options.get('guid'):
            params['guid'] = options['guid']
        if options.get('type'):
            params['type'] = options['type']
        if options.get('query'):
            params['q'] = options['query']
        pages = range(1, self.get_max_pages(params) + 1)

        if options.get('max'):
            pages = pages[: options.get('max')]

        print('Fetching pages from 1 to %s' % max(pages))
        for page in pages:
            self._get_addons_from_page(page, params)
