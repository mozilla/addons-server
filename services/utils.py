from datetime import datetime, timedelta
import settings_local as settings
import posixpath
import re

# Ugh. But this avoids any zamboni or django imports at all.
# Perhaps we can import these without any problems and we can
# remove all this.

from constants.applications import APPS_ALL
from constants.platforms import PLATFORMS
from constants.base import (STATUS_NULL, STATUS_UNREVIEWED, STATUS_PENDING,
                            STATUS_NOMINATED, STATUS_PUBLIC, STATUS_DISABLED,
                            STATUS_LISTED, STATUS_BETA, STATUS_LITE,
                            STATUS_LITE_AND_NOMINATED, STATUS_PURGATORY,
                            VERSION_BETA)

APP_GUIDS = dict([(app.guid, app.id) for app in APPS_ALL.values()])
PLATFORMS = dict([(plat.api_name, plat.id) for plat in PLATFORMS.values()])

ADDON_SLUGS_UPDATE = {
    1: 'extension',
    2: 'theme',
    3: 'extension',
    4: 'search',
    5: 'item',
    6: 'extension',
    7: 'plugin'}


STATUSES_PUBLIC = {'STATUS_PUBLIC': STATUS_PUBLIC,
                   'STATUS_LITE': STATUS_LITE,
                   'STATUS_LITE_AND_NOMINATED': STATUS_LITE_AND_NOMINATED}


version_re = re.compile(r"""(?P<major>\d+)         # major (x in x.y)
                            \.(?P<minor1>\d+)      # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version""",
                        re.VERBOSE)


def get_mirror(status, id, row):
    if row['datestatuschanged']:
        published = datetime.now() - row['datestatuschanged']
    else:
        published = timedelta(minutes=0)

    if row['disabled_by_user'] or status == STATUS_DISABLED:
        host = settings.PRIVATE_MIRROR_URL
    elif (status == STATUS_PUBLIC
          and not row['disabled_by_user']
          and row['file_status'] in (STATUS_PUBLIC, STATUS_BETA)
          and published > timedelta(minutes=settings.MIRROR_DELAY)
          and not settings.DEBUG):
        host = settings.MIRROR_URL
    else:
        host = settings.LOCAL_MIRROR_URL

    return posixpath.join(host, str(id), row['filename'])
