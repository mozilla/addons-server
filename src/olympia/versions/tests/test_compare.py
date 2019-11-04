# -*- coding: utf-8 -*-
from olympia.versions.compare import (
    addon_version_int, MAX_VERSION_PART, version_dict, version_int)


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    assert version_int('3.5.0a1pre2') == 3050000001002
    assert version_int('') == 200100
    assert version_int('0') == 200100
    assert version_int('*') == 65535000000200100
    assert version_int(MAX_VERSION_PART) == 65535000000200100
    assert version_int(MAX_VERSION_PART + 1) == 65535000000200100


def test_version_int_compare():
    assert version_int('3.6.*') == version_int('3.6.99')
    assert version_int('3.6.*') > version_int('3.6.8')
    assert version_int('*') == version_int('65535')
    assert version_int('98.*') < version_int('*')
    assert version_int('5.*') == version_int('5.99')
    assert version_int('5.*') > version_int('5.0.*')


def test_addon_version_int_hash():
    assert addon_version_int('3.5.0a1pre2') == 0x30005000000000000102
    assert addon_version_int('') == 0x2000010
    assert addon_version_int('0') == 0x2000010
    assert addon_version_int('*') == 0xFFFF0000000000002000010
    assert addon_version_int(MAX_VERSION_PART) == 0xFFFF0000000000002000010
    assert addon_version_int('*.65535.65535.65535') == (
        0xFFFFFFFFFFFFFFFF2000010)
    assert addon_version_int('*.65535.65635.65535a65535pre9') == (
        0xFFFFFFFFFFFFFFFF0FFFF09)


def test_addon_version_int_compare():
    assert addon_version_int('3.6.*') == addon_version_int('3.6.65535')
    assert addon_version_int('3.6.*') > addon_version_int('3.6.8')
    assert addon_version_int('*') == addon_version_int('65535')
    assert addon_version_int('*') == addon_version_int('65536')  # over max.
    assert addon_version_int('98.*') < addon_version_int('*')
    assert addon_version_int('65534.*') < addon_version_int('*')
    assert addon_version_int('5.*') == addon_version_int('5.65535')
    assert addon_version_int('5.*') > addon_version_int('5.0.*')


def test_version_dict():
    assert version_dict('5.0.*') == (
        {'major': 5,
         'minor1': 0,
         'minor2': 65535,
         'minor3': None,
         'alpha': None,
         'alpha_ver': None,
         'pre': None,
         'pre_ver': None})

    assert version_dict('5.0.*', asterisk_value=1234) == (
        {'major': 5,
         'minor1': 0,
         'minor2': 1234,
         'minor3': None,
         'alpha': None,
         'alpha_ver': None,
         'pre': None,
         'pre_ver': None})

    assert version_dict('*.0.*', major_asterisk_value=5678) == (
        {'major': 5678,
         'minor1': 0,
         'minor2': 65535,
         'minor3': None,
         'alpha': None,
         'alpha_ver': None,
         'pre': None,
         'pre_ver': None})


def test_version_int_unicode():
    assert version_int(u'\u2322 ugh stephend') == 200100
