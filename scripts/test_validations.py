from datetime import datetime
from random import shuffle

from validations import (automated_count_pipeline, automated_validations,
                         parse_validations, reduce_pipeline,
                         severe_validations, unlisted_validations)

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

LISTED1 = {'metadata': {'id': '10', 'listed': True}}
LISTED2 = {'metadata': {'id': '33', 'listed': True}}
AUTO1 = {'metadata': {'id': '25', 'listed': True},
         'passed_auto_validation': False}
AUTO2 = {'metadata': {'id': '50', 'listed': False},
         'passed_auto_validation': True}
AUTO3 = {'metadata': {'id': '71', 'listed': True},
         'passed_auto_validation': True}
UNLISTED1 = {'metadata': {'id': '90', 'listed': False}}
UNLISTED2 = {'metadata': {'id': '81', 'listed': True}}
VALIDATIONS = [LISTED1, LISTED2, AUTO1, AUTO2, AUTO3, UNLISTED1, UNLISTED2]
now = datetime.now().date()
for validation in VALIDATIONS:
    validation['date'] = now
UNLISTED_ADDONS_SET = set(['25', '50', '71', '81'])
LITE_ADDONS_SET = set(['33', '25', '50', '71'])
shuffle(VALIDATIONS)


def test_automated_validations():
    results = automated_validations(
        VALIDATIONS,
        unlisted_addons=UNLISTED_ADDONS_SET,
        lite_addons=LITE_ADDONS_SET)

    def addon_id(v):
        return v['metadata']['id']
    assert sorted(results, key=addon_id) == [AUTO1, AUTO2, AUTO3]


def test_automated_signing_count():
    count = reduce_pipeline(
        automated_count_pipeline(unlisted_addons=UNLISTED_ADDONS_SET,
                                 lite_addons=LITE_ADDONS_SET,
                                 load_file=lambda f: VALIDATIONS),
        ['file1.txt'])

    assert count == [{'total': 3, 'passed': 2, 'failed': 1, 'date': now}]
