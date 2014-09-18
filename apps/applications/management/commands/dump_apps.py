import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage as storage
import commonware.log
import amo
from applications.models import AppVersion

log = commonware.log.getLogger('z.cron')


# The validator uses the file created here to keep up to date with the
# apps and versions on AMO.
class Command(BaseCommand):
    help = 'Dump a json file containing AMO apps and versions.'

    JSON_PATH = os.path.join(settings.MEDIA_ROOT, 'apps.json')

    def handle(self, *args, **kw):
        apps = {}
        for id, app in amo.APP_IDS.iteritems():
            apps[id] = dict(guid=app.guid, versions=[],
                            name=amo.APPS_ALL[id].short)
        versions = (AppVersion.objects.values_list('application', 'version')
                    .order_by('version_int'))
        for app, version in versions:
            try:
                apps[app]['versions'].append(version)
            except KeyError:
                # Sunbird is still in the database but shouldn't show up here.
                pass

        # Local file, to be read by validator.
        with storage.open(self.JSON_PATH, 'w') as f:
            json.dump(apps, f)
            log.debug("Wrote: %s" % f.name)
