import requests
from os.path import basename
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.management.base import BaseCommand, CommandError
from django.db.transaction import atomic

from olympia import amo
from olympia.amo.tests import version_factory
from olympia.addons.models import Addon


class KeyboardInterruptError(Exception):
    pass


class Command(BaseCommand):
    """Download and save all AMO add-ons public data."""
    VERSIONS_API_URL = (
        'https://addons.mozilla.org/api/v4/addons/addon/%(slug)s/versions/'
    )

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'As a safety precaution this command only works if DEBUG=True.'
            )
        self.fetch_versions_data(**options)

    def get_max_pages(self, slug):
        response = requests.get(self.VERSIONS_API_URL % {'slug': slug})
        return response.json()['page_count']

    def fetch_versions_data(self, **options):
        self.addon = Addon.objects.get(slug=options['slug'])
        slug = self.addon.slug
        pages = range(1, self.get_max_pages(slug) + 1)
        print('Fetching pages from 1 to %s' % max(pages))
        for page in pages:
            self._get_versions_from_page(slug, page)

    def _get_versions_from_page(self, slug, page):
        data = []
        print('fetching %s' % page)
        query_params = {
            'page': page
        }
        response = requests.get(
            self.VERSIONS_API_URL % {'slug': slug}, params=query_params)
        print('fetched %s' % page)

        for version in response.json()['results']:
            self._handle_version(version)

        return data

    def _download_file(self, url, file_):
        with storage.open(file_.current_file_path, 'wb') as f:
            data = requests.get(url)
            f.write(data.content)

    def _handle_version(self, data):
        if self.addon.versions(manager='unfiltered_for_relations').filter(
                version=data['version']).exists():
            print('Skipping %s (version already exists' % data['version'])
            return

        files_data = data['files'][0]
        file_kw = {
            'hash': files_data['hash'],
            'filename': basename(urlparse(files_data['url']).path),
            'status': amo.STATUS_CHOICES_API_LOOKUP[files_data['status']],
            'platform': amo.PLATFORM_DICT[files_data['platform']].id,
            'size': files_data['size'],
            'is_webextension': files_data['is_webextension'],
            'is_mozilla_signed_extension': (
                files_data['is_mozilla_signed_extension']),
            'strict_compatibility': (
                data['is_strict_compatibility_enabled'])
        }

        version_kw = {
            'version': data['version'],
            # FIXME: maybe reviewed/created would make sense at least, to
            # get more or less the correct ordering ?
            # Everything else we don't really care about at the moment.
        }

        print('Creating version %s' % data['version'])
        with atomic():
            version = version_factory(
                addon=self.addon, file_kw=file_kw, **version_kw)

            # Download the file to the right path.
            print('Downloading file for version %s' % data['version'])
            self._download_file(files_data['url'], version.files.all()[0])
