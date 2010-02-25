import re


version_re = re.compile(r"""(?P<major>\d+)      # major (x in x.y)
                            \.(?P<minor1>\d+)   # minor1 (y in x.y)
                            \.?(?P<minor2>\d+)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)   # alpha/beta
                            (?P<alpha_ver>\d*)  # alpha/beta version
                            (?P<pre>pre)?       # pre release
                            (?P<pre_ver>\d)?    # pre release version""",
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
            d[num] = int(d[num]) if d[num] else None
    else:
        d = dict((k, None) for k in numbers)
        d.update((k, None) for k in letters)
    return d
