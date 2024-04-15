import pytest

from olympia.versions.compare import (
    APP_MAJOR_VERSION_PART_MAX,
    VersionString,
    version_dict,
    version_int,
)


def test_version_int():
    """Tests that version_int outputs correct integer values."""
    assert version_int('3.5.0a1pre2') == 3050000001002
    assert version_int('') == 200100
    assert version_int('0') == 200100
    assert version_int('*') == 65535999999200100
    assert version_int('*.0') == 65535000000200100
    assert version_int(APP_MAJOR_VERSION_PART_MAX) == 65535000000200100
    assert version_int(APP_MAJOR_VERSION_PART_MAX + 1) == 65535000000200100
    assert version_int(f'{APP_MAJOR_VERSION_PART_MAX}.100') == 65535990000200100


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
    assert version_int('100.0') > version_int('99.0')
    assert version_int('101.0') > version_int('100.0')
    assert version_int('101.0') > version_int('100.0.1')
    assert version_int('101.0') > version_int('100.1')


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
        assert VersionString('100.0') > VersionString('99.0')
        assert VersionString('100.1') > VersionString('100.0.1')
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

    def test_vparts(self):
        assert VersionString('3.6a5pre9').vparts == (
            VersionString.Part('3'),
            VersionString.Part('6a5pre9'),
        )


class TestVersionStringPart:
    def test_parse(self):
        assert VersionString.Part('1').asdict() == {'a': 1, 'b': '', 'c': 0, 'd': ''}
        assert VersionString.Part('1pre').asdict() == {
            'a': 1,
            'b': 'pre',
            'c': 0,
            'd': '',
        }
        assert VersionString.Part('5pre4').asdict() == {
            'a': 5,
            'b': 'pre',
            'c': 4,
            'd': '',
        }
        assert VersionString.Part('11pre4').asdict() == {
            'a': 11,
            'b': 'pre',
            'c': 4,
            'd': '',
        }
        assert VersionString.Part('567pre123').asdict() == {
            'a': 567,
            'b': 'pre',
            'c': 123,
            'd': '',
        }
        assert VersionString.Part('-567pre123').asdict() == {
            'a': -567,
            'b': 'pre',
            'c': 123,
            'd': '',
        }
        assert VersionString.Part('-567pre-123').asdict() == {
            'a': -567,
            'b': 'pre',
            'c': -123,
            'd': '',
        }
        assert VersionString.Part('1pre1b').asdict() == {
            'a': 1,
            'b': 'pre',
            'c': 1,
            'd': 'b',
        }
        assert VersionString.Part('1pre1aa').asdict() == {
            'a': 1,
            'b': 'pre',
            'c': 1,
            'd': 'aa',
        }
        assert VersionString.Part('6a5pre').asdict() == {
            'a': 6,
            'b': 'a',
            'c': 5,
            'd': 'pre',
        }
        # Edge cases
        assert VersionString.Part('1pre0').asdict() == {
            'a': 1,
            'b': 'pre',
            'c': 0,
            'd': '',
        }
        assert VersionString.Part('00').asdict() == {'a': 0, 'b': '', 'c': 0, 'd': ''}
        assert VersionString.Part('01').asdict() == {'a': 1, 'b': '', 'c': 0, 'd': ''}
        assert VersionString.Part('001').asdict() == {'a': 1, 'b': '', 'c': 0, 'd': ''}
        assert VersionString.Part('-1').asdict() == {'a': -1, 'b': '', 'c': 0, 'd': ''}
        # + has a special meaning for backwards compatability
        assert VersionString.Part('5+').asdict() == {
            'a': 6,
            'b': 'pre',
            'c': 0,
            'd': '',
        }
        assert VersionString.Part('0+').asdict() == {
            'a': 1,
            'b': 'pre',
            'c': 0,
            'd': '',
        }

    def test_equality(self):
        assert VersionString.Part('567pre123a') == VersionString.Part('567pre123a')
        assert VersionString.Part('') == VersionString.Part('')
        assert VersionString.Part('1') == VersionString.Part('1')
        assert VersionString.Part('*') == VersionString.Part('*')
        assert VersionString.Part('01') == VersionString.Part('1')
        # Special case where + is treated differently
        assert VersionString.Part('23+') == VersionString.Part('24pre')

        assert VersionString.Part('1') != VersionString.Part('2')
        assert VersionString.Part('1a') != VersionString.Part('1')
        assert VersionString.Part('1a1') != VersionString.Part('1a')
        assert VersionString.Part('1a1a') != VersionString.Part('1a1')
        assert VersionString.Part('1a1a') != VersionString.Part('1a1b')

    def test_comparison(self):
        # Asterisks are treated seperately
        assert VersionString.Part('*') > VersionString.Part('9999')
        assert VersionString.Part('*') > VersionString.Part('0')
        assert VersionString.Part('*') > VersionString.Part('')
        assert not VersionString.Part('*') > VersionString.Part('*')
        # Only a-part
        assert VersionString.Part('31') > VersionString.Part('30')
        assert VersionString.Part('31') < VersionString.Part('32')
        assert VersionString.Part('1') > VersionString.Part('0')
        assert VersionString.Part('1') > VersionString.Part('')
        # a-b parts
        assert VersionString.Part('40bb') > VersionString.Part('40ba')
        # a-b with parts missing
        assert VersionString.Part('40') > VersionString.Part('40a')
        assert VersionString.Part('41a') > VersionString.Part('40')
        # a-b-c parts
        assert VersionString.Part('26hi72') > VersionString.Part('26hi71')
        assert VersionString.Part('26hi72') > VersionString.Part('26hh73')
        assert VersionString.Part('26hi72') > VersionString.Part('25hj73')
        # a-b-c parts with parts missing
        assert VersionString.Part('26a') > VersionString.Part('26a1')
        assert VersionString.Part('26') > VersionString.Part('26a1')
        assert VersionString.Part('27a1') > VersionString.Part('26b')
        assert VersionString.Part('27a1') > VersionString.Part('26')
        # a-b-c-d parts
        assert VersionString.Part('5b6c') > VersionString.Part('5b6b')
        assert VersionString.Part('5b6c') > VersionString.Part('5b5d')
        assert VersionString.Part('5b6c') > VersionString.Part('5a7d')
        assert VersionString.Part('5b6c') > VersionString.Part('4c7d')
        # a-b-c-d parts with parts missing
        assert VersionString.Part('5b6') > VersionString.Part('5b6a')
        assert VersionString.Part('5b') > VersionString.Part('5b1a')
        assert VersionString.Part('5') > VersionString.Part('5a1a')
        assert VersionString.Part('6a1a') > VersionString.Part('5b2')
        assert VersionString.Part('6a1a') > VersionString.Part('5b')
        assert VersionString.Part('6a1a') > VersionString.Part('5')


@pytest.mark.parametrize(
    'version',
    (
        '1.0',
        '1.2.3.4',
        '2.0a1',
        '0.2.0b1',
        '40007.2024.3.42c',
        '1.01b.78',
        '1.2.5_5',
        '714.16G',
        '999999999999999999999999999999',
    ),
)
def test_version_string_back_to_str(version):
    vs = VersionString(version)
    assert vs == VersionString('.'.join(str(part) for part in vs.vparts))
    assert str(vs) == version


def test_version_dict():
    assert version_dict('5.0.*') == (
        {
            'major': 5,
            'minor1': 0,
            'minor2': '*',
            'minor3': None,
            'alpha': None,
            'alpha_ver': None,
            'pre': None,
            'pre_ver': None,
        }
    )


def test_version_int_unicode():
    assert version_int('\u2322 ugh stephend') == 200100
