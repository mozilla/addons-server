import datetime
import json
import os
import pytest
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.core.files.storage import default_storage as storage

from freezegun import freeze_time
from waffle.testutils import override_switch

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.blocklist.cron import (
    auto_import_blocklist, get_blocklist_last_modified_time,
    upload_mlbf_to_kinto)
from olympia.blocklist.mlbf import MLBF
from olympia.blocklist.models import Block
from olympia.constants.blocklist import (
    MLBF_TIME_CONFIG_KEY, MLBF_BASE_ID_CONFIG_KEY)
from olympia.lib.kinto import KintoServer
from olympia.zadmin.models import get_config, set_config


@freeze_time('2020-01-01 12:34:56')
@override_switch('blocklist_mlbf_submit', active=True)
class TestUploadToKinto(TestCase):
    def setUp(self):
        addon_factory()
        self.block = Block.objects.create(
            addon=addon_factory(
                version_kw={'version': '1.2b3'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        delete_patcher = mock.patch.object(KintoServer, 'delete_all_records')
        attach_patcher = mock.patch.object(KintoServer, 'publish_attachment')
        record_patcher = mock.patch.object(KintoServer, 'publish_record')
        self.addCleanup(delete_patcher.stop)
        self.addCleanup(attach_patcher.stop)
        self.addCleanup(record_patcher.stop)
        self.delete_mock = delete_patcher.start()
        self.publish_attachment_mock = attach_patcher.start()
        self.publish_record_mock = record_patcher.start()

    def test_no_previous_mlbf(self):
        upload_mlbf_to_kinto()

        generation_time = int(
            datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)
        self.publish_attachment_mock.assert_called_with(
            {'key_format': MLBF.KEY_FORMAT,
             'generation_time': generation_time,
             'attachment_type': 'bloomfilter-base'},
            ('filter.bin', mock.ANY, 'application/octet-stream'))
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            generation_time)
        assert (
            get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) ==
            generation_time)
        self.publish_record_mock.assert_not_called()
        self.delete_mock.assert_called_once()

        gen_path = os.path.join(
            settings.MLBF_STORAGE_PATH, str(generation_time))
        assert os.path.getsize(os.path.join(gen_path, 'filter'))
        assert os.path.getsize(os.path.join(gen_path, 'blocked.json'))
        assert os.path.getsize(os.path.join(gen_path, 'notblocked.json'))
        # no stash because no previous mlbf
        assert not os.path.exists(os.path.join(gen_path, 'stash.json'))

    def test_stash_because_previous_mlbf(self):
        set_config(MLBF_TIME_CONFIG_KEY, 123456, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, 123456, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '123456', 'blocked.json')
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump(['madeup@guid:123'], blocked_file)

        upload_mlbf_to_kinto()

        generation_time = int(
            datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)

        self.publish_attachment_mock.assert_called_with(
            {'key_format': MLBF.KEY_FORMAT,
             'generation_time': generation_time,
             'attachment_type': 'bloomfilter-full'},
            ('filter.bin', mock.ANY, 'application/octet-stream'))
        self.publish_record_mock.assert_called_with({
            'key_format': MLBF.KEY_FORMAT,
            'stash_time': generation_time,
            'stash': {
                'blocked': [
                    f'{self.block.guid}:'
                    f'{self.block.addon.current_version.version}'],
                'unblocked': ['madeup@guid:123']}
        })
        self.delete_mock.assert_not_called()
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            generation_time)
        assert (
            get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) ==
            123456)

    def test_stash_because_many_mlbf(self):
        set_config(MLBF_TIME_CONFIG_KEY, 123456, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, 987654, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '123456', 'blocked.json')
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump(['madeup@guid:12345'], blocked_file)
        base_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '987654', 'blocked.json')
        with storage.open(base_blocked_path, 'w') as blocked_file:
            json.dump([], blocked_file)

        upload_mlbf_to_kinto()

        generation_time = int(
            datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)

        self.publish_attachment_mock.assert_called_with(
            {'key_format': MLBF.KEY_FORMAT,
             'generation_time': generation_time,
             'attachment_type': 'bloomfilter-full'},
            ('filter.bin', mock.ANY, 'application/octet-stream'))
        self.publish_record_mock.assert_called_with({
            'key_format': MLBF.KEY_FORMAT,
            'stash_time': generation_time,
            'stash': {
                'blocked': [
                    f'{self.block.guid}:'
                    f'{self.block.addon.current_version.version}'],
                'unblocked': ['madeup@guid:12345']}
        })
        self.delete_mock.assert_not_called()
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            generation_time)
        assert (
            get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) ==
            987654)

    @mock.patch.object(MLBF, 'should_reset_base_filter')
    def test_reset_base_because_over_reset_threshold(self, should_reset_mock):
        should_reset_mock.return_value = True
        set_config(MLBF_TIME_CONFIG_KEY, 123456, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, 987654, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '123456', 'blocked.json')
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump(['madeup@guid:12345'], blocked_file)
        base_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '987654', 'blocked.json')
        with storage.open(base_blocked_path, 'w') as blocked_file:
            json.dump([], blocked_file)

        upload_mlbf_to_kinto()

        generation_time = int(
            datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)

        self.publish_attachment_mock.assert_called_with(
            {'key_format': MLBF.KEY_FORMAT,
             'generation_time': generation_time,
             'attachment_type': 'bloomfilter-base'},
            ('filter.bin', mock.ANY, 'application/octet-stream'))
        self.publish_record_mock.assert_not_called()
        self.delete_mock.assert_called_once()
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            generation_time)
        assert (
            get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) ==
            generation_time)

        gen_path = os.path.join(
            settings.MLBF_STORAGE_PATH, str(generation_time))
        # no stash because we're starting with a new base mlbf
        assert not os.path.exists(os.path.join(gen_path, 'stash.json'))

    @override_switch('blocklist_mlbf_submit', active=False)
    def test_waffle_off_disables_publishing(self):
        upload_mlbf_to_kinto()

        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_not_called()
        assert not get_config(MLBF_TIME_CONFIG_KEY)

    @freeze_time('2020-01-01 12:34:56', as_arg=True)
    def test_no_block_changes(frozen_time, self):
        # This was the last time the mlbf was generated
        last_time = int(
            (frozen_time() - timedelta(seconds=1)).timestamp() * 1000)
        # And the Block was modified just that before so would be included
        self.block.update(modified=(frozen_time() - timedelta(seconds=2)))
        set_config(MLBF_TIME_CONFIG_KEY, last_time, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, str(last_time), 'blocked.json')
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump([f'{self.block.guid}:1.2b3'], blocked_file)

        upload_mlbf_to_kinto()
        # So no need for a new bloomfilter
        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_not_called()

        # But if we add a new Block a new filter is needed
        addon_factory()
        Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        upload_mlbf_to_kinto()
        self.publish_attachment_mock.assert_called_once()
        assert (
            get_config(MLBF_TIME_CONFIG_KEY, json_value=True) ==
            int(datetime.datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000))

        frozen_time.tick()
        # If the first block is deleted the last_modified date won't have
        # changed, but the number of blocks will, so trigger a new filter.
        last_modified = get_blocklist_last_modified_time()
        self.block.delete()
        assert last_modified == get_blocklist_last_modified_time()
        upload_mlbf_to_kinto()
        assert self.publish_attachment_mock.call_count == 2  # called again


@pytest.mark.django_db
@mock.patch('olympia.blocklist.cron.call_command')
def test_auto_import_blocklist_waffle(call_command_mock):
    with override_switch('blocklist_auto_import', active=False):
        auto_import_blocklist()
        call_command_mock.assert_not_called()

    with override_switch('blocklist_auto_import', active=True):
        auto_import_blocklist()
        call_command_mock.assert_called()
