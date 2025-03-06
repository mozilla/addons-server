from django.core.files.base import ContentFile
from django.db.transaction import atomic

import requests

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import version_factory
from olympia.landfill.management.commands import BaseLandfillCommand


class KeyboardInterruptError(Exception):
    pass


class Command(BaseLandfillCommand):
    """Download versions for a particular add-on from AMO public data."""

    VERSIONS_API_URL = (
        'https://addons.mozilla.org/api/v5/addons/addon/%(slug)s/versions/'
    )

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str)
        parser.add_argument(
            '--overwrite-existing-versions', action='store_true', default=False
        )

    def handle(self, *args, **options):
        self.assert_local_dev_mode()
        self.options = options
        self.fetch_versions_data()

    def get_max_pages(self, slug):
        response = requests.get(self.VERSIONS_API_URL % {'slug': slug})
        return response.json()['page_count']

    def fetch_versions_data(self):
        self.addon = Addon.objects.get(slug=self.options['slug'])
        slug = self.addon.slug
        pages = range(1, self.get_max_pages(slug) + 1)
        print('Fetching pages from 1 to %s' % max(pages))
        for page in pages:
            self._get_versions_from_page(slug, page)

    def _get_versions_from_page(self, slug, page):
        data = []
        print('fetching %s' % page)
        query_params = {'page': page}
        response = requests.get(
            self.VERSIONS_API_URL % {'slug': slug}, params=query_params
        )
        print('fetched %s' % page)

        for version in response.json()['results']:
            self._handle_version(version)

        return data

    def _download_file(self, url):
        data = requests.get(url)
        return data.content

    def _handle_version(self, data):
        if (
            version := self.addon.versions(manager='unfiltered_for_relations')
            .filter(version=data['version'])
            .last()
        ):
            if self.options.get('overwrite_existing_versions'):
                print('Hard-deleting existing version %s in database' % data['version'])
                version.delete(hard=True)
            else:
                print('Skipping %s (version already exists)' % data['version'])
                return

        file_data = data['file']

        # Download the file to the right path.
        print('Downloading file for version %s' % data['version'])
        raw_file_contents = self._download_file(file_data['url'])

        file_kw = {
            'hash': file_data['hash'],
            'status': amo.STATUS_CHOICES_API_LOOKUP[file_data['status']],
            'size': file_data['size'],
            'is_mozilla_signed_extension': (file_data['is_mozilla_signed_extension']),
            'strict_compatibility': (data['is_strict_compatibility_enabled']),
            # The name argument to the ContentFile doesn't matter, it will be
            # ignored and we'll dynamically build one from the upload_to
            # callback, but it needs to be set for things to work.
            'file': ContentFile(raw_file_contents, name='addon.xpi'),
        }

        version_kw = {
            'version': data['version'],
            # FIXME: maybe reviewed/created would make sense at least, to
            # get more or less the correct ordering ?
            # Everything else we don't really care about at the moment.
        }

        with atomic():
            print('Creating version %s' % data['version'])
            version_factory(addon=self.addon, file_kw=file_kw, **version_kw)
