import re

from versions.compare import version_re


def floor_version(s):
    result = s
    if result:
        s = s.replace('.x', '.0').replace('.*', '.0').replace('*', '.0')
        match = re.match(version_re, s)
        if match:
            major, minor = match.groups()[:2]
            major, minor = int(major), int(minor or 0)
            result = '%s.%s' % (major, minor)
    return result
