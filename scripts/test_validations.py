from nose.tools import eq_

import validations as v

TEST_ADDON_LISTED_FALSE = {'metadata': {'listed': False, 'id': 'wat'}}
TEST_ADDON_UNLISTED_ID = {'metadata': {'id': 'baz'}}
TEST_ADDONS = [
    {'metadata': {'listed': True, 'id': 'yo'}},
    TEST_ADDON_LISTED_FALSE,
    {'metadata': {'id': 'foobar'}},
    TEST_ADDON_UNLISTED_ID,
]


def test_parse_validations():
    results = v.parse_validations([
        '{"foo":"bar"}\n',
        '["baz",1,{"wat":99}]\n'
    ])
    eq_(list(results), [{'foo': 'bar'}, ['baz', 1, {'wat': 99}]])


def test_unlisted_validations_without_unlisted_addons():
    unlisted = v.unlisted_validations(TEST_ADDONS, set())
    eq_(list(unlisted), [TEST_ADDON_LISTED_FALSE])


def test_unlisted_validations_with_unlisted_addons():
    unlisted = v.unlisted_validations(TEST_ADDONS, set(['baz', 'wat']))
    eq_(list(unlisted), [TEST_ADDON_LISTED_FALSE, TEST_ADDON_UNLISTED_ID])


def test_severe_validations():
    nope = {'signing_summary':
            {'high': 0, 'medium': 0, 'trivial': 0, 'low': 0}}
    minor = {'signing_summary':
             {'high': 0, 'medium': 0, 'trivial': 0, 'low': 1}}
    trivial = {'signing_summary':
               {'high': 0, 'medium': 0, 'trivial': 1, 'low': 0}}
    severe = {'signing_summary':
              {'high': 10, 'medium': 0, 'trivial': 0, 'low': 0}}
    results = v.severe_validations([nope, trivial, minor, nope, severe, nope])
    eq_(list(results), [minor, severe])
