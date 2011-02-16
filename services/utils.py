from datetime import datetime, timedelta
import settings_local as settings
import posixpath
import re

# Ugh. But this avoids any zamboni or django imports at all.
# Perhaps we can import these without any problems and we can
# remove all this.

APP_GUIDS = {
    '{3550f703-e582-4d05-9a08-453d09bdfdc6}': 18,
    '{718e30fb-e89b-41dd-9da7-e25a45638b28}': 52,
    '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}': 2,
    '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}': 59,
    '{a23983c0-fd0e-11dc-95ff-0800200c9a66}': 60,
    '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}': 1}

PLATFORMS = {
    'Linux': 2,
    'BSD_OS': 4,
    'Darwin': 3,
    'WINNT': 5,
    'SunOS': 6,
    'Android': 7,
    'Maemo': 8}

STATUS_NULL = 0
STATUS_UNREVIEWED = 1
STATUS_PENDING = 2
STATUS_NOMINATED = 3
STATUS_PUBLIC = 4
STATUS_DISABLED = 5
STATUS_LISTED = 6
STATUS_BETA = 7
STATUS_LITE = 8
STATUS_LITE_AND_NOMINATED = 9
STATUS_PURGATORY = 10

ADDON_SLUGS_UPDATE = {
    1: 'extension',
    2: 'theme',
    3: 'extension',
    4: 'search',
    5: 'item',
    6: 'extension',
    7: 'plugin'}


STATUSES_PUBLIC = {'STATUS_PUBLIC': '4',
                   'STATUS_LITE': '8',
                   'STATUS_LITE_AND_NOMINATED': '9'}


version_re = re.compile(r"""(?P<major>\d+)         # major (x in x.y)
                            \.(?P<minor1>\d+)      # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version""",
                        re.VERBOSE)


VERSION_BETA = re.compile('(a|alpha|b|beta|pre|rc)\d*$')


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
