import re

from django.utils.encoding import force_bytes


MAXVERSION = 2 ** 63 - 1

version_re = re.compile(
    r"""(?P<major>\d+|\*)      # major (x in x.y)
                            \.?(?P<minor1>\d+|\*)? # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version
                        """,
    re.VERBOSE,
)


def dict_from_int(version_int):
    """Converts a version integer into a dictionary with major/minor/...
    info."""
    d = {}
    rem = version_int
    (rem, d['pre_ver']) = divmod(rem, 100)
    (rem, d['pre']) = divmod(rem, 10)
    (rem, d['alpha_ver']) = divmod(rem, 100)
    (rem, d['alpha']) = divmod(rem, 10)
    (rem, d['minor3']) = divmod(rem, 100)
    (rem, d['minor2']) = divmod(rem, 100)
    (rem, d['minor1']) = divmod(rem, 100)
    (rem, d['major']) = divmod(rem, 100)
    d['pre'] = None if d['pre'] else 'pre'
    d['alpha'] = {0: 'a', 1: 'b'}.get(d['alpha'])

    return d


def num(vint):
    return '{major}.{minor1}.{minor2}.{minor3}'.format(**dict_from_int(vint))


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


def version_int(version):
    d = version_dict(force_bytes(version))
    for key in ['alpha_ver', 'major', 'minor1', 'minor2', 'minor3', 'pre_ver']:
        if not d[key]:
            d[key] = 0
    atrans = {'a': 0, 'b': 1}
    d['alpha'] = atrans.get(d['alpha'], 2)
    d['pre'] = 0 if d['pre'] else 1

    v = "%d%02d%02d%02d%d%02d%d%02d" % (
        d['major'],
        d['minor1'],
        d['minor2'],
        d['minor3'],
        d['alpha'],
        d['alpha_ver'],
        d['pre'],
        d['pre_ver'],
    )
    return min(int(v), MAXVERSION)
