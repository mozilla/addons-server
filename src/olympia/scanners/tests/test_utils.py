import pytest

from olympia.scanners.utils import default_from_schema


@pytest.mark.parametrize(
    'schema, expected_obj',
    (
        (None, {}),
        ({}, {}),
        ('foo', {}),
        ([], {}),
        ({'type': 'object'}, {}),
        ({'type': 'object', 'keys': {}}, {}),
        ({'type': 'array', 'items': {'type': 'string'}}, {}),
    ),
)
def test_default_from_schema_empty(schema, expected_obj):
    assert default_from_schema(schema) == expected_obj


def test_default_from_schema_with_keys_but_no_default():
    schema = {
        'type': 'object',
        'keys': {
            'foo': {'type': 'string'},
        },
    }
    assert default_from_schema(schema) == {}


def test_default_from_schema_with_default():
    schema = {
        'type': 'object',
        'keys': {
            'ignoreme': {
                'type': 'string',
            },
            'foo': {'type': 'string', 'default': 'bar'},
        },
    }
    assert default_from_schema(schema) == {'foo': 'bar'}
