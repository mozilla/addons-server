from django.core.management.base import BaseCommand

from pyquery import PyQuery

from olympia.applications.models import AppVersion
from olympia.constants.applications import APP_GUIDS


class Command(BaseCommand):
    help = 'Import the application versions created on addons.mozilla.org.'

    def handle(self, *args, **options):
        log = self.stdout.write
        doc = PyQuery(
            url='https://addons.mozilla.org/en-US/firefox/pages/appversions/')
        codes = doc('.prose ul li code')
        for i in range(0, len(codes), 2):
            try:
                app = APP_GUIDS[codes[i].text]
            except KeyError:
                # Unknown app, ignore.
                continue
            log('Import versions for {0}'.format(app.short))
            versions = codes[i + 1].text.split(', ')
            for version in versions:
                AppVersion.objects.get_or_create(application=app.id,
                                                 version=version)
