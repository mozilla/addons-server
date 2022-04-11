from io import BytesIO

import pytest
from babel.messages.extract import DEFAULT_KEYWORDS

from olympia.core.babel import extract_jinja, generate_option


@pytest.mark.parametrize(
    'value,expected',
    [
        (True, 'true'),
        (False, 'false'),
        ('foo', 'foo'),
        (['foo', 'bar'], 'foo,bar'),
        (('abc', 'def'), 'abc,def'),
    ],
)
def test_generate_option(value, expected):
    assert generate_option(value) == expected


def test_extract_jinja_no_options():
    # Doesn't actually extract, just tests that extract_jinja() doesn't fail
    # when converting our settings in options for the underlying function.
    extract_jinja(BytesIO(), DEFAULT_KEYWORDS, ['L10n:'], {})
