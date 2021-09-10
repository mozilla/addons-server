from datetime import datetime
from unittest import mock

import pytest

from olympia.amo.tests import user_factory
from olympia.blocklist.models import Block
from olympia.blocklist.utils import (
    datetime_to_ts,
    legacy_delete_blocks,
    legacy_publish_blocks,
)
from olympia.lib.remote_settings import RemoteSettings


@pytest.mark.django_db
@mock.patch.object(RemoteSettings, 'publish_record')
def test_legacy_publish_blocks(publish_mock):
    publish_mock.return_value = {'id': 'a-legacy-id'}
    block_new = Block.objects.create(guid='new@guid', updated_by=user_factory())
    block_regex = Block.objects.create(
        guid='regex@guid', updated_by=user_factory(), legacy_id='*regex'
    )
    block_update = Block.objects.create(
        guid='update@guid', updated_by=user_factory(), legacy_id='update'
    )

    data = {
        'details': {'bug': '', 'why': '', 'name': ''},
        'enabled': True,
        'versionRange': [
            {
                'severity': 3,
                'minVersion': '0',
                'maxVersion': '*',
            }
        ],
    }

    legacy_publish_blocks([block_new, block_regex, block_update])
    assert publish_mock.call_args_list == [
        mock.call(dict(guid='new@guid', **data)),
        mock.call(dict(guid='update@guid', **data), 'update'),
    ]
    assert block_new.legacy_id == 'a-legacy-id'
    assert block_regex.legacy_id == '*regex'  # not changed
    assert block_update.legacy_id == 'update'  # not changed


@pytest.mark.django_db
@mock.patch.object(RemoteSettings, 'delete_record')
def test_legacy_delete_blocks(delete_record_mock):
    block = Block.objects.create(
        guid='legacy@guid', updated_by=user_factory(), legacy_id='legacy'
    )
    block_regex = Block.objects.create(
        guid='regex@guid', updated_by=user_factory(), legacy_id='*regex'
    )
    block_not_legacy = Block.objects.create(guid='not@guid', updated_by=user_factory())

    legacy_delete_blocks([block, block_regex, block_not_legacy])
    assert delete_record_mock.call_args_list == [mock.call('legacy')]
    assert block.legacy_id == ''
    assert block_regex.legacy_id == ''  # cleared anyway


def test_datetime_to_ts():
    now = datetime.now()
    assert datetime_to_ts(now) == int(now.timestamp() * 1000)
