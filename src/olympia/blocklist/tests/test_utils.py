from unittest import mock

import pytest

from olympia import amo
from olympia.amo.tests import addon_factory, user_factory, version_factory
from olympia.blocklist.models import Block
from olympia.blocklist.utils import (
    get_all_guids, get_blocked_guids, hash_filter_inputs, legacy_delete_blocks,
    legacy_publish_blocks)
from olympia.files.models import File
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

    legacy_publish_blocks(
        [block_new, block_regex, block_legacy_dropped, block_never_legacy,
         block_update])
    assert publish_mock.call_args_list == [
        mock.call(dict(guid='new@guid', **data)),
        mock.call(dict(guid='regex@guid', **data)),
        mock.call(dict(guid='update@guid', **data), 'update')]
    assert delete_mock.call_args_list == [
        mock.call('dropped_legacy')]
    assert block_new.kinto_id == 'a-kinto-id'
    assert block_regex.kinto_id == 'a-kinto-id'  # it'd be unique if not mocked
    assert block_legacy_dropped.kinto_id == ''
    assert block_update.kinto_id == 'update'  # it's not changed


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


@pytest.mark.django_db
def test_get_blocked_guids():
    for idx in range(0, 10):
        addon_factory()
    # one version, 0 - *
    Block.objects.create(
        addon=addon_factory(),
        updated_by=user_factory())
    # one version, 0 - 9999
    Block.objects.create(
        addon=addon_factory(),
        updated_by=user_factory(),
        max_version='9999')
    # one version, 0 - *, unlisted
    Block.objects.create(
        addon=addon_factory(
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED}),
        updated_by=user_factory())
    # three versions, but only two within block (123.40, 123.5)
    three_ver = Block.objects.create(
        addon=addon_factory(
            version_kw={'version': '123.40'}),
        updated_by=user_factory(), max_version='123.45')
    version_factory(
        addon=three_ver.addon, version='123.5')
    version_factory(
        addon=three_ver.addon, version='123.45.1')
    # no matching versions (edge cases)
    over = Block.objects.create(
        addon=addon_factory(),
        updated_by=user_factory(),
        max_version='0')
    under = Block.objects.create(
        addon=addon_factory(),
        updated_by=user_factory(),
        min_version='9999')

    all_guids = get_all_guids()
    assert len(all_guids) == File.objects.count() == 10 + 8
    assert (three_ver.guid, '123.40') in all_guids
    assert (three_ver.guid, '123.5') in all_guids
    assert (three_ver.guid, '123.45.1') in all_guids
    over_tuple = (over.guid, over.addon.current_version.version)
    under_tuple = (under.guid, under.addon.current_version.version)
    assert over_tuple in all_guids
    assert under_tuple in all_guids

    blocked_guids = get_blocked_guids()
    assert len(blocked_guids) == 5
    assert (three_ver.guid, '123.40') in blocked_guids
    assert (three_ver.guid, '123.5') in blocked_guids
    assert (three_ver.guid, '123.45.1') not in blocked_guids
    assert over_tuple not in blocked_guids
    assert under_tuple not in blocked_guids


def test_hash_filter_inputs():
    data = [
        ('guid@', '1.0'),
        ('foo@baa', '999.223a'),
    ]
    assert hash_filter_inputs(data, 37872) == [
        '37872:guid@:1.0',
        '37872:foo@baa:999.223a',
    ]
