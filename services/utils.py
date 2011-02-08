from datetime import datetime, timedelta
import settings_services as settings
import posixpath
import re

# Ugh. But this avoids any zamboni or django imports at all.
# Perhaps we can import these without any problems and we can
# remove all this.

APP_GUIDS = {
    '{3550f703-e582-4d05-9a08-453d09bdfdc6}': 1,
    '{718e30fb-e89b-41dd-9da7-e25a45638b28}': 2,
    '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}': 3,
    '{a23983c0-fd0e-11dc-95ff-0800200c9a66}': 4,
    '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}': 5}

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

version_re = re.compile(r"""(?P<major>\d+)         # major (x in x.y)
                            \.(?P<minor1>\d+)      # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version""",
                        re.VERBOSE)


def version_dict(version):
    """Turn a version string into a dict with major/minor/... info."""
    match = version_re.match(version or '')
    letters = 'alpha pre'.split()
    numbers = 'major minor1 minor2 minor3 alpha_ver pre_ver'.split()
    if match:
        d = match.groupdict()
        for letter in letters:
            d[letter] = d[letter] if d[letter] else None
        for num in numbers:
            if d[num] == '*':
                d[num] = 99
            else:
                d[num] = int(d[num]) if d[num] else None
    else:
        d = dict((k, None) for k in numbers)
        d.update((k, None) for k in letters)
    return d


# Cheap cache, version_int was showing up as the 8th most expensive call.
_version_cache = {}


def version_int(version):
    if version in _version_cache:
        return _version_cache[version]

    d = version_dict(str(version))
    for key in ['alpha_ver', 'major', 'minor1', 'minor2', 'minor3',
                'pre_ver']:
        if not d[key]:
            d[key] = 0
    atrans = {'a': 0, 'b': 1}
    d['alpha'] = atrans.get(d['alpha'], 2)
    d['pre'] = 0 if d['pre'] else 1

    v = "%d%02d%02d%02d%d%02d%d%02d" % (d['major'], d['minor1'],
            d['minor2'], d['minor3'], d['alpha'], d['alpha_ver'], d['pre'],
            d['pre_ver'])

    _version_cache[version] = int(v)
    return int(v)


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
          and status in (STATUS_PUBLIC, STATUS_BETA)
          and published > timedelta(minutes=settings.MIRROR_DELAY)
          and not settings.DEBUG):
        host = settings.MIRROR_URL
    else:
        host = settings.LOCAL_MIRROR_URL

    return posixpath.join(host, str(id), row['filename'])
