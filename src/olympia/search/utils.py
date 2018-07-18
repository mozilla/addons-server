import re

from olympia.versions.compare import version_re


def floor_version(version):
    if version:
        version = (
            unicode(version)
            .replace('.x', '.0')
            .replace('.*', '.0')
            .replace('*', '.0')
        )
        match = re.match(version_re, version)
        if match:
            major, minor = match.groups()[:2]
            major, minor = int(major), int(minor or 0)
            version = '%s.%s' % (major, minor)
    return version
