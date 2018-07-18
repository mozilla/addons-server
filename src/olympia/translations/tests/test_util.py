import pytest

from olympia.translations.models import Translation
from olympia.translations.utils import (
    transfield_changed,
    truncate,
    truncate_text,
)


pytestmark = pytest.mark.django_db


def test_truncate_text():
    assert truncate_text('foobar', 5) == ('fooba...', 0)
    assert truncate_text('foobar', 5, True) == ('fooba...', 0)
    assert truncate_text('foobar', 5, True, 'xxx') == ('foobaxxx', 0)
    assert truncate_text('foobar', 6) == ('foobar...', 0)
    assert truncate_text('foobar', 7) == ('foobar', 1)


def test_truncate():
    s = '   <p>one</p><ol><li>two</li><li> three</li> </ol> four <p>five</p>'

    assert truncate(s, 100) == s
    assert truncate(s, 6) == '<p>one</p><ol><li>two...</li></ol>'
    assert truncate(s, 5, True) == '<p>one</p><ol><li>tw...</li></ol>'
    assert truncate(s, 11) == (
        '<p>one</p><ol><li>two</li><li>three...</li></ol>'
    )
    assert truncate(s, 15) == (
        '<p>one</p><ol><li>two</li><li>three</li></ol>four...'
    )
    assert truncate(s, 13, True, 'xxx') == (
        '<p>one</p><ol><li>two</li><li>three</li></ol>foxxx'
    )


def test_transfield_changed():
    initial = {
        'some_field': 'some_val',
        'name_en-us': Translation.objects.create(
            id=500, locale='en-us', localized_string='test_name'
        ),
    }
    data = {
        'some_field': 'some_val',
        'name': {'init': '', 'en-us': 'test_name'},
    }

    # No change.
    assert transfield_changed('name', initial, data) == 0

    # Changed localization.
    data['name']['en-us'] = 'test_name_changed'
    assert transfield_changed('name', initial, data) == 1

    # New localization.
    data['name']['en-us'] = 'test_name'
    data['name']['en-af'] = Translation.objects.create(
        id=505, locale='en-af', localized_string='test_name_localized'
    )
    assert transfield_changed('name', initial, data) == 1

    # Deleted localization.
    del initial['name_en-us']
    assert transfield_changed('name', initial, data) == 1
