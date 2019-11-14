import re

from django.utils.encoding import force_text


BIGINT_POSITIVE_MAX = 2 ** 63 - 1
MAX_VERSION_PART = 2 ** 16 - 1

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


def version_dict(version, asterisk_value=MAX_VERSION_PART,
                 major_asterisk_value=None):
    """Turn a version string into a dict with major/minor/... info."""
    major_asterisk_value = major_asterisk_value or asterisk_value
    match = version_re.match(version or '')

    if match:
        vdict = match.groupdict()
        for letter in LETTERS:
            vdict[letter] = vdict[letter] if vdict[letter] else None
        for num in NUMBERS:
            if vdict[num] == '*':
                vdict[num] = (
                    major_asterisk_value if num == 'major' else asterisk_value)
            else:
                vdict[num] = int(vdict[num]) if vdict[num] else None
    else:
        vdict = {number_part: None for number_part in NUMBERS}
        vdict.update((letter_part, None) for letter_part in LETTERS)
    return vdict


def _get_version_dict(version_string, max_number_minor, max_number_major):
    vdict = version_dict(
        force_text(version_string), asterisk_value=max_number_minor,
        major_asterisk_value=max_number_major)
    for num in NUMBERS:
        max_num = max_number_major if num == 'major' else max_number_minor
        vdict[num] = min(vdict[num] or 0, max_num)
    vdict['alpha'] = {'a': 0, 'b': 1}.get(vdict['alpha'], 2)
    vdict['pre'] = 0 if vdict['pre'] else 1
    return vdict


def version_int(version):
    """This is used for converting an app version's version string into a
    single number for comparison.  To maintain compatibility the minor parts
    are limited to 99 making it unsuitable for comparing addon version strings.
    """
    vdict = _get_version_dict(
        version, max_number_minor=99, max_number_major=MAX_VERSION_PART)

    vint = '%d%02d%02d%02d%d%02d%d%02d' % (
        vdict['major'], vdict['minor1'], vdict['minor2'], vdict['minor3'],
        vdict['alpha'], vdict['alpha_ver'], vdict['pre'], vdict['pre_ver'])
    return min(int(vint), BIGINT_POSITIVE_MAX)


def addon_version_int(version):
    """Suitable for comparing addon version strings that are Chrome compatible
    plus the limited a, b, pre suffixes we support for app versions.  Returns
    a very large integer (that's too big to store as a BIGINT in mysql).
    """
    vdict = _get_version_dict(
        version, max_number_minor=MAX_VERSION_PART,
        max_number_major=MAX_VERSION_PART)

    # use hex numbers to simplify the conversion.
    # alpha and pre can only be 0,1,2 so will always be a single digit; pre_var
    # is parsed as single digit by version_dict.
    hex_string = ('%x' '%04x' '%04x' '%04x' '%x' '%04x' '%x' '%x') % (
        vdict['major'], vdict['minor1'], vdict['minor2'], vdict['minor3'],
        vdict['alpha'], vdict['alpha_ver'], vdict['pre'], vdict['pre_ver'])
    return int(hex_string, base=16)
