from unittest import mock

import pytest

from olympia.amo.tests import user_factory
from olympia.blocklist.models import Block
from olympia.blocklist.utils import (
    legacy_delete_blocks, legacy_publish_blocks, split_regex_to_list)
from olympia.lib.kinto import KintoServer


@pytest.mark.django_db
@mock.patch.object(KintoServer, 'publish_record')
@mock.patch.object(KintoServer, 'delete_record')
def test_legacy_publish_blocks(delete_mock, publish_mock):
    publish_mock.return_value = {'id': 'a-kinto-id'}
    block_new = Block.objects.create(
        guid='new@guid', include_in_legacy=True, updated_by=user_factory())
    block_regex = Block.objects.create(
        guid='regex@guid', include_in_legacy=True, updated_by=user_factory(),
        kinto_id='*regex')
    block_legacy_dropped = Block.objects.create(
        guid='drop@guid', include_in_legacy=False, updated_by=user_factory(),
        kinto_id='dropped_legacy')
    block_legacy_dropped_regex = Block.objects.create(
        guid='rgdrop@guid', include_in_legacy=False, updated_by=user_factory(),
        kinto_id='*dropped_legacy')
    block_never_legacy = Block.objects.create(
        guid='never@guid', include_in_legacy=False, updated_by=user_factory())
    block_update = Block.objects.create(
        guid='update@guid', include_in_legacy=True, updated_by=user_factory(),
        kinto_id='update')
    # Currently we don't ever mix include_in_legacy=True and False together,
    # but the function should handle it.
    data = {
        'details': {
            'bug': '',
            'why': '',
            'name': ''
        },
        'enabled': True,
        'versionRange': [{
            'severity': 3,
            'minVersion': '0',
            'maxVersion': '*',
        }],
    }

    legacy_publish_blocks([
        block_new,
        block_regex,
        block_legacy_dropped,
        block_legacy_dropped_regex,
        block_never_legacy,
        block_update])
    assert publish_mock.call_args_list == [
        mock.call(dict(guid='new@guid', **data)),
        mock.call(dict(guid='update@guid', **data), 'update')]
    assert delete_mock.call_args_list == [
        mock.call('dropped_legacy')]
    assert block_new.kinto_id == 'a-kinto-id'
    assert block_regex.kinto_id == '*regex'  # not changed
    assert block_legacy_dropped_regex.kinto_id == ''  # cleared anyway
    assert block_legacy_dropped.kinto_id == ''
    assert block_update.kinto_id == 'update'  # not changed


@pytest.mark.django_db
@mock.patch.object(KintoServer, 'delete_record')
def test_legacy_delete_blocks(delete_record_mock):
    block = Block.objects.create(
        guid='legacy@guid', include_in_legacy=True, updated_by=user_factory(),
        kinto_id='legacy')
    block_regex = Block.objects.create(
        guid='regex@guid', include_in_legacy=True, updated_by=user_factory(),
        kinto_id='*regex')
    block_not_legacy = Block.objects.create(
        guid='not@guid', include_in_legacy=False, updated_by=user_factory(),
        kinto_id='not_legacy')
    block_not_imported = Block.objects.create(
        guid='new@guid', include_in_legacy=True, updated_by=user_factory())

    legacy_delete_blocks(
        [block, block_regex, block_not_legacy, block_not_imported])
    assert delete_record_mock.call_args_list == [mock.call('legacy')]
    assert block.kinto_id == ''
    assert block_regex.kinto_id == ''  # cleared anyway


def test_split_regex_to_list():
    regex_list = (
        '^('
        '(\\{df59cc82-3d49-4d2c-8069-70a7d71d387a\\})|'
        '(\\{ef78ae03-b232-46c0-8715-d562db1ace23\\})|'
        '(\\{98f556db-837c-489e-9c45-a06a6997492c\\})'
        ')$'
    )
    assert split_regex_to_list(regex_list) == [
        '{df59cc82-3d49-4d2c-8069-70a7d71d387a}',
        '{ef78ae03-b232-46c0-8715-d562db1ace23}',
        '{98f556db-837c-489e-9c45-a06a6997492c}',
    ]

    regex_no_outer_brackets_list = (
        '^'
        '(\\{df59cc82-3d49-4d2c-8069-70a7d71d387a\\})|'
        '(\\{ef78ae03-b232-46c0-8715-d562db1ace23\\})|'
        '(\\{98f556db-837c-489e-9c45-a06a6997492c\\})'
        '$'
    )
    assert split_regex_to_list(regex_no_outer_brackets_list) == [
        '{df59cc82-3d49-4d2c-8069-70a7d71d387a}',
        '{ef78ae03-b232-46c0-8715-d562db1ace23}',
        '{98f556db-837c-489e-9c45-a06a6997492c}',
    ]

    real_regex = '^pink@.*\\.info$'
    assert split_regex_to_list(real_regex) is None

    real_regex_brackets = '^(pink@.*\\.info)$'
    assert split_regex_to_list(real_regex_brackets) is None
