import re

from django.utils.encoding import force_text


MAXVERSION = 2 ** 63 - 1

version_re = re.compile(r"""(?P<major>\d+|\*)      # major (x in x.y)
                            \.?(?P<minor1>\d+|\*)? # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version
                        """,
                        re.VERBOSE)

LETTERS = ['alpha', 'pre']
NUMBERS = ['major', 'minor1', 'minor2', 'minor3', 'alpha_ver', 'pre_ver']


def version_dict(version):
    """Turn a version string into a dict with major/minor/... info."""
    match = version_re.match(version or '')

    if match:
        vdict = match.groupdict()
        for letter in LETTERS:
            vdict[letter] = vdict[letter] if vdict[letter] else None
        for num in NUMBERS:
            if vdict[num] == '*':
                vdict[num] = 99
            else:
                vdict[num] = int(vdict[num]) if vdict[num] else None
    else:
        vdict = {number_part: None for number_part in NUMBERS}
        vdict.update((letter_part, None) for letter_part in LETTERS)
    return vdict


def version_int(version):
    vdict = version_dict(force_text(version))
    for key in NUMBERS:
        if not vdict[key]:
            vdict[key] = 0
    vdict['alpha'] = {'a': 0, 'b': 1}.get(vdict['alpha'], 2)
    vdict['pre'] = 0 if vdict['pre'] else 1

    vint = '%d%02d%02d%02d%d%02d%d%02d' % (
        vdict['major'], vdict['minor1'], vdict['minor2'], vdict['minor3'],
        vdict['alpha'], vdict['alpha_ver'], vdict['pre'], vdict['pre_ver'])
    return min(int(vint), MAXVERSION)
