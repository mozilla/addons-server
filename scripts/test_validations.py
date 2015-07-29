from validations import (parse_validations, severe_validations,
                         unlisted_validations)

TEST_ADDON_LISTED_FALSE = {'metadata': {'listed': False, 'id': 'wat'}}
TEST_ADDON_UNLISTED_ID = {'metadata': {'id': 'baz'}}
TEST_ADDONS = [
    {'metadata': {'listed': True, 'id': 'yo'}},
    TEST_ADDON_LISTED_FALSE,
    {'metadata': {'id': 'foobar'}},
    TEST_ADDON_UNLISTED_ID,
]


def test_parse_validations():
    results = parse_validations([
        '{"foo":"bar"}\n',
        '["baz",1,{"wat":99}]\n'
    ])
    assert list(results) == [{'foo': 'bar'}, ['baz', 1, {'wat': 99}]]


def test_unlisted_validations_without_unlisted_addons():
    unlisted = unlisted_validations(TEST_ADDONS, set())
    assert list(unlisted) == [TEST_ADDON_LISTED_FALSE]


def test_unlisted_validations_with_unlisted_addons():
    unlisted = unlisted_validations(TEST_ADDONS, set(['baz', 'wat']))
    assert list(unlisted) == [TEST_ADDON_LISTED_FALSE, TEST_ADDON_UNLISTED_ID]


def test_severe_validations():
    nope = {'signing_summary':
            {'high': 0, 'medium': 0, 'trivial': 0, 'low': 0}}
    minor = {'signing_summary':
             {'high': 0, 'medium': 0, 'trivial': 0, 'low': 1}}
    trivial = {'signing_summary':
               {'high': 0, 'medium': 0, 'trivial': 1, 'low': 0}}
    severe = {'signing_summary':
              {'high': 10, 'medium': 0, 'trivial': 0, 'low': 0}}
    results = severe_validations([nope, trivial, minor, nope, severe, nope])
    assert list(results) == [minor, severe]
