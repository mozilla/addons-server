# -*- coding: utf-8 -*-
from olympia.versions.compare import (
    MAXVERSION,
    dict_from_int,
    version_dict,
    version_int,
)


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    assert version_int('3.5.0a1pre2') == 3050000001002
    assert version_int('') == 200100
    assert version_int('0') == 200100
    assert version_int('*') == 99000000200100
    assert version_int(MAXVERSION) == MAXVERSION
    assert version_int(MAXVERSION + 1) == MAXVERSION
    assert version_int('9999999') == MAXVERSION


def test_version_int_compare():
    assert version_int('3.6.*') == version_int('3.6.99')
    assert version_int('3.6.*') > version_int('3.6.8')


def test_version_asterix_compare():
    assert version_int('*') == version_int('99')
    assert version_int('98.*') < version_int('*')
    assert version_int('5.*') == version_int('5.99')
    assert version_int('5.*') > version_int('5.0.*')


def test_version_dict():
    assert version_dict('5.0') == (
        {
            'major': 5,
            'minor1': 0,
            'minor2': None,
            'minor3': None,
            'alpha': None,
            'alpha_ver': None,
            'pre': None,
            'pre_ver': None,
        }
    )


def test_version_int_unicode():
    assert version_int(u'\u2322 ugh stephend') == 200100


def test_dict_from_int():
    d = dict_from_int(3050000001002)
    assert d['major'] == 3
    assert d['minor1'] == 5
    assert d['minor2'] == 0
    assert d['minor3'] == 0
    assert d['alpha'] == 'a'
    assert d['alpha_ver'] == 1
    assert d['pre'] == 'pre'
    assert d['pre_ver'] == 2
