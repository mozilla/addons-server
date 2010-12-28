import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

import commonware.log
import amo
from applications.models import Application, AppVersion

log = commonware.log.getLogger('z.cron')

# The validator uses the file created here to keep up to date with the
# apps and versions on AMO.
class Command(BaseCommand):
    help = 'Dump a json file containing AMO apps and versions.'

    JSON_PATH = os.path.join(settings.NETAPP_STORAGE, 'apps.json')

    def handle(self, *args, **kw):
        apps = {}
        for id, guid in Application.objects.values_list('id', 'guid'):
            apps[id] = dict(guid=guid, versions=[],
                            name=amo.APPS_ALL[id].short)
        versions = (AppVersion.objects.values_list('application', 'version')
                    .order_by('version_int'))
        for app, version in versions:
            apps[app]['versions'].append(version)
        apps[amo.FIREFOX.id]['versions'].append('4.0.*')  # bug 613234
        with open(self.JSON_PATH, 'w') as f:
            json.dump(apps, f)
            log.debug("Wrote: %s" % f.name)
