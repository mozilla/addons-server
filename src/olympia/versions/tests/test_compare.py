# -*- coding: utf-8 -*-
from olympia.versions.compare import (
    MAX_VERSION_PART,
    version_dict,
    version_int,
    VersionString,
)


def test_version_int():
    """Tests that version_int outputs correct integer values."""
    assert version_int('3.5.0a1pre2') == 3050000001002
    assert version_int('') == 200100
    assert version_int('0') == 200100
    assert version_int('*') == 65535999999200100
    assert version_int('*.0') == 65535000000200100
    assert version_int(MAX_VERSION_PART) == 65535000000200100
    assert version_int(MAX_VERSION_PART + 1) == 65535000000200100
    assert version_int(f'{MAX_VERSION_PART}.100') == 65535990000200100


def test_version_int_compare():
    assert version_int('3.6.0.*') == version_int('3.6.0.99')
    assert version_int('3.6.*.0') == version_int('3.6.99')
    assert version_int('3.6.*') > version_int('3.6.8')
    assert version_int('3.6.*') > version_int('3.6.99.98')
    assert version_int('*') == version_int('65535.99.99.99')
    assert version_int('*.0') == version_int('65535')
    assert version_int('98.*') < version_int('*')
    assert version_int('5.*.0') == version_int('5.99')
    assert version_int('5.*') > version_int('5.0.*')


class TestVersionString:
    def test_equality(self):
        assert VersionString('3.6.0.0') == VersionString('3.6')
        assert VersionString('3.6.*.0') != VersionString('3.6.*')
        assert VersionString('*') == VersionString('*.*.*.*')
        assert VersionString('*.0.0.0') != VersionString('65535')
        assert VersionString('3.6.*') != VersionString('3.6.65535')
        assert VersionString('*') != VersionString('65535.65535.65535.65535')
        assert VersionString('*') != VersionString('65535.0.0.0')
        assert VersionString('3.6a5pre9') != VersionString('3.6')
        # edge cases with falsey values
        assert VersionString('0') != ''
        assert VersionString('') != '0'
        assert VersionString('0') is not None
        assert VersionString('') is not None
        none = None
        assert VersionString('0') != none
        assert VersionString('') != none

    def test_comparison(self):
        assert VersionString('3.6.*') > VersionString('3.6.8')
        assert VersionString('3.6.*') > VersionString('3.6.65535')
        assert VersionString('*') > VersionString('65535.0.0.1')
        assert VersionString('*') > VersionString('65536.65536.65536.65536')
        assert VersionString('*') > VersionString('98.*')
        assert VersionString('98.*') < VersionString('*')
        assert VersionString('65534.*') < VersionString('*')
        assert VersionString('5.*') > VersionString('5.0.*')
        assert VersionString('3.6a5pre9') < VersionString('3.6')
        assert VersionString('3.6a5pre9') < VersionString('3.6b1')
        assert VersionString('3.6.*') > VersionString('3.6a5pre9')
        assert VersionString('99.99999999b1') > VersionString('99.99999998b1')
        assert VersionString('99999999.99b1') > VersionString('99999998.99b1')
        assert VersionString('*') > VersionString('99999998.99b1')

    def test_bool(self):
        # bool(VersionString(x)) should behave like bool(x)
        assert bool(VersionString('')) is False
        assert bool(VersionString('0')) is True
        assert bool(VersionString(0)) is True
        assert bool(VersionString('false')) is True
        assert bool(VersionString('False')) is True
        assert bool(VersionString('something')) is True
        assert bool(VersionString('3.6.*')) is True
        assert bool(VersionString('3.6')) is True
        assert bool(VersionString('*')) is True

    def test_parts(self):
        assert tuple(VersionString('3.6a5pre9').parts) == (
            ('major', 3),
            ('minor1', 6),
            ('minor2', 0),
            ('minor3', 0),
            ('alpha', 'a'),
            ('alpha_ver', 5),
            ('pre', 'pre'),
            ('pre_ver', 9),
        )
        assert tuple(VersionString('3.6.*').parts) == (
            ('major', 3),
            ('minor1', 6),
            ('minor2', '*'),
            ('minor3', '*'),
            ('alpha', ''),
            ('alpha_ver', 0),
            ('pre', ''),
            ('pre_ver', 0),
        )

    def test_part_indexing(self):
        vs = VersionString('32.6pre9')
        assert vs['major'] == 32
        assert vs['minor3'] == 0
        assert vs['alpha'] == ''
        assert vs['pre'] == 'pre'
        assert vs['pre_ver'] == 9
        assert vs[0] == '3'  # normal string indexing still works
        assert vs[3:5] == '6p'


def test_version_dict():
    assert version_dict('5.0.*') == (
        {
            'major': 5,
            'minor1': 0,
            'minor2': 65535,
            'minor3': None,
            'alpha': None,
            'alpha_ver': None,
            'pre': None,
            'pre_ver': None,
        }
    )

    assert version_dict('5.0.*', asterisk_value=1234) == (
        {
            'major': 5,
            'minor1': 0,
            'minor2': 1234,
            'minor3': None,
            'alpha': None,
            'alpha_ver': None,
            'pre': None,
            'pre_ver': None,
        }
    )

    assert version_dict('*.0.*', asterisk_value='@') == (
        {
            'major': '@',
            'minor1': 0,
            'minor2': '@',
            'minor3': None,
            'alpha': None,
            'alpha_ver': None,
            'pre': None,
            'pre_ver': None,
        }
    )


def test_version_int_unicode():
    assert version_int('\u2322 ugh stephend') == 200100
