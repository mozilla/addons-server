from django.core.exceptions import BadRequest
from django.core.management.base import BaseCommand

import requests

from olympia import amo
from olympia.applications.models import AppVersion


class Command(BaseCommand):
    help = 'Import the application versions created on addons.mozilla.org.'
    url = 'https://addons.mozilla.org/api/v5/applications/{}/'

    def handle(self, *args, **options):
        log = self.stdout.write

        for app in amo.APP_USAGE:
            log(f'Starting to import versions for {app.short}')
            response = requests.get(self.url.format(app.short))
            if (status := response.status_code) != 200:
                raise BadRequest(f'Importing versions from AMO prod failed: {status}.')
            try:
                data = response.json() or {}
                if (guid := data.get('guid')) != app.guid:
                    raise BadRequest(
                        'Importing versions from AMO prod failed: '
                        f'guid mistmatch - expected={app.guid}; got={guid}.'
                    )
                versions = data.get('versions')

            except requests.exceptions.JSONDecodeError:
                versions = None
            if not versions or len(versions) == 0:
                raise BadRequest(
                    'Importing versions from AMO prod failed: no versions.'
                )

            for version in versions:
                AppVersion.objects.get_or_create(application=app.id, version=version)
            log(f'Added {len(versions)} versions for {app.short}.')
