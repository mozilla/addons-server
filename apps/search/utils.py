import subprocess
import zlib
import re

from django.conf import settings

from amo import constants as const


def reindex():
    """
    Reindexes sphinx.  Note this is only to be used in dev and test
    environments.
    """

    subprocess.call([settings.SPHINX_INDEXER, '--all', '--rotate',
        '--config', settings.SPHINX_CONFIG_PATH])


def start_sphinx():
    """
    Starts sphinx.  Note this is only to be used in dev and test environments.
    """

    subprocess.Popen([settings.SPHINX_SEARCHD, '--config',
        settings.SPHINX_CONFIG_PATH])


def stop_sphinx():
    """
    Stops sphinx.  Note this is only to be used in dev and test environments.
    """

    subprocess.call([settings.SPHINX_SEARCHD, '--stop', '--config',
        settings.SPHINX_CONFIG_PATH])

pattern = re.compile(r"""(\d+)   # major (x in x.y)
                         \.(\d+)   # minor1 (y in x.y)
                         \.?(\d+)? # minor2 (z in x.y.z)
                         \.?(\d+)? # minor3 (w in x.y.z.w)
                         ([a|b]?)  # alpha/beta
                         (\d*)     # alpha/beta version
                         (pre)?    # pre release
                         (\d)?     # pre release version""", re.VERBOSE)
pattern_plus = re.compile(r'((\d+)\+)')


def convert_type(type):
    if type == 'extension' or type == 'extensions':
        return const.ADDON_EXTENSIONS
    elif type == 'theme' or type == 'themes':
        return const.ADDON_THEME
    elif type == 'dict' or type == 'dicts':
        return const.ADDON_DICT
    elif type == 'language' or type == 'languages':
        return const.ADDON_LPAPP
    elif type == 'plugin' or type == 'plugins':
        return const.ADDON_PLUGIN


def convert_version(version_string):
    """
    This will enumerate a version so that it can be used for comparisons and
    indexing.
    """

    # Replace .x or .* with .99 since these are equivalent.
    version_string = version_string.replace('.x', '.99')
    version_string = version_string.replace('.*', '.99')

    # Replace \d+\+ with $1++pre0 (e.g. 2.1+ => 2.2pre0).

    match = re.search(pattern_plus, version_string)

    if match:
        (old, ver) = match.groups()
        replacement = "%dpre0" % (int(ver) + 1)
        version_string = version_string.replace(old, replacement)

    # Now we break up a version into components.
    #
    # e.g. 3.7.2.1b3pre3
    # we break into:
    # major => 3
    # minor1 => 7
    # minor2 => 2
    # minor3 => 1
    # alpha => b => 1
    # alpha_n => 3
    # pre => 0
    # pre_n => 3
    #
    # Alpha is 0,1,2 based on whether a version is alpha, beta or a release.
    # Pre is 0 or 1.  0 indicates that this is a pre-release.
    #
    # The numbers are chosen based on sorting rules, not for any deep meaning.

    match = re.match(pattern, version_string)

    if match:
        (major, minor1, minor2, minor3, alpha, alpha_n, pre,
            pre_n) = match.groups()

        # normalize data
        major  = int(major)
        minor1 = int(minor1)
        minor2 = int(minor2) if minor2 else 0
        minor3 = int(minor3) if minor3 else 0

        if alpha == 'a':
            alpha = 0
        elif alpha == 'b':
            alpha = 1
        else:
            alpha = 2

        if alpha_n:
            alpha_n = int(alpha_n)
        else:
            alpha_n = 0

        if pre == 'pre':
            pre = 0
        else:
            pre = 1

        if pre_n:
            pre_n = int(pre_n)
        else:
            pre_n = 0

        # We recombine everything into a single large integer.
        int_str = ("%02d%02d%02d%02d%d%02d%d%02d"
            % (major, minor1, minor2, minor3, alpha, alpha_n, pre, pre_n) )

        return int(int_str)


crc32 = lambda x: zlib.crc32(x) & 0xffffffff
