from nose.tools import eq_

from translations.models import Translation
from translations.utils import transfield_changed, truncate


def test_truncate():
    s = '   <p>one</p><ol><li>two</li><li> three</li> </ol><p> four five</p>'

    eq_(truncate(s, 100), s)
    eq_(truncate(s, 6), '   <p>one</p><ol><li>two...</li></ol>')
    eq_(truncate(s, 11), '   <p>one</p><ol><li>two</li><li>three...</li></ol>')


def test_transfield_changed():
    initial = {
        'some_field': 'some_val',
        'name_en-us': Translation.objects.create(
            id=500, locale='en-us', localized_string='test_name')
    }
    data = {'some_field': 'some_val',
            'name': {'init': '', 'en-us': 'test_name'}}

    # No change.
    eq_(transfield_changed('name', initial, data), 0)

    # Changed localization.
    data['name']['en-us'] = 'test_name_changed'
    eq_(transfield_changed('name', initial, data), 1)

    # New localization.
    data['name']['en-us'] = 'test_name'
    data['name']['en-af'] = Translation.objects.create(
        id=505, locale='en-af', localized_string='test_name_localized')
    eq_(transfield_changed('name', initial, data), 1)

    # Deleted localization.
    del initial['name_en-us']
    eq_(transfield_changed('name', initial, data), 1)
