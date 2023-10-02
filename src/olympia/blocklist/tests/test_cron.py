import json
import os
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core.files.storage import default_storage as storage

import pytest
from freezegun import freeze_time
from waffle.testutils import override_switch

from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.cron import (
    get_blocklist_last_modified_time,
    process_blocklistsubmissions,
    upload_mlbf_to_remote_settings,
)
from olympia.blocklist.mlbf import MLBF
from olympia.blocklist.models import Block, BlocklistSubmission
from olympia.constants.blocklist import MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY
from olympia.lib.remote_settings import RemoteSettings
from olympia.zadmin.models import get_config, set_config


STATSD_PREFIX = 'blocklist.cron.upload_mlbf_to_remote_settings.'


@freeze_time('2020-01-01 12:34:56')
@override_switch('blocklist_mlbf_submit', active=True)
class TestUploadToRemoteSettings(TestCase):
    def setUp(self):
        addon = addon_factory()
        version_factory(addon=addon)
        version_factory(addon=addon)
        self.block = block_factory(
            addon=addon_factory(
                version_kw={'version': '1.2b3'},
                file_kw={'is_signed': True},
            ),
            updated_by=user_factory(),
        )
        delete_patcher = mock.patch.object(RemoteSettings, 'delete_all_records')
        attach_patcher = mock.patch.object(RemoteSettings, 'publish_attachment')
        record_patcher = mock.patch.object(RemoteSettings, 'publish_record')
        statsd_incr_patcher = mock.patch('olympia.blocklist.cron.statsd.incr')
        cleanup_files_patcher = mock.patch(
            'olympia.blocklist.cron.cleanup_old_files.delay'
        )
        self.addCleanup(delete_patcher.stop)
        self.addCleanup(attach_patcher.stop)
        self.addCleanup(record_patcher.stop)
        self.addCleanup(statsd_incr_patcher.stop)
        self.addCleanup(cleanup_files_patcher.stop)
        self.delete_mock = delete_patcher.start()
        self.publish_attachment_mock = attach_patcher.start()
        self.publish_record_mock = record_patcher.start()
        self.statsd_incr_mock = statsd_incr_patcher.start()
        self.cleanup_files_mock = cleanup_files_patcher.start()

    def test_no_previous_mlbf(self):
        with self.assertNumQueries(16):
            # Mainly config gets/saves and savepoints; regression check.
            upload_mlbf_to_remote_settings()

        generation_time = int(datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)
        self.publish_attachment_mock.assert_called_with(
            {
                'key_format': MLBF.KEY_FORMAT,
                'generation_time': generation_time,
                'attachment_type': 'bloomfilter-base',
            },
            ('filter.bin', mock.ANY, 'application/octet-stream'),
        )
        assert get_config(MLBF_TIME_CONFIG_KEY, json_value=True) == generation_time
        assert get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) == generation_time
        self.publish_record_mock.assert_not_called()
        self.delete_mock.assert_called_once()

        gen_path = os.path.join(settings.MLBF_STORAGE_PATH, str(generation_time))
        assert os.path.getsize(os.path.join(gen_path, 'filter'))
        assert os.path.getsize(os.path.join(gen_path, 'blocked.json'))
        assert os.path.getsize(os.path.join(gen_path, 'notblocked.json'))
        # no stash because no previous mlbf
        assert not os.path.exists(os.path.join(gen_path, 'stash.json'))

        self.statsd_incr_mock.assert_has_calls(
            [
                mock.call(f'{STATSD_PREFIX}blocked_changed', 1),
                mock.call(f'{STATSD_PREFIX}blocked_count', 1),
                mock.call(f'{STATSD_PREFIX}not_blocked_count', 3),
                mock.call('blocklist.tasks.upload_filter.reset_collection'),
                mock.call('blocklist.tasks.upload_filter.upload_mlbf'),
                mock.call('blocklist.tasks.upload_filter.upload_mlbf.base'),
                mock.call(f'{STATSD_PREFIX}success'),
            ]
        )
        self.cleanup_files_mock.assert_not_called()

    def test_stash_because_previous_mlbf(self):
        set_config(MLBF_TIME_CONFIG_KEY, 123456, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, 123456, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '123456', 'blocked.json'
        )
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump(['madeup@guid:123'], blocked_file)

        with self.assertNumQueries(8):
            # Mainly config gets/saves and savepoints; regression check.
            upload_mlbf_to_remote_settings()

        generation_time = int(datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)

        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_called_with(
            {
                'key_format': MLBF.KEY_FORMAT,
                'stash_time': generation_time,
                'stash': {
                    'blocked': [
                        f'{self.block.guid}:'
                        f'{self.block.addon.current_version.version}'
                    ],
                    'unblocked': ['madeup@guid:123'],
                },
            }
        )
        self.delete_mock.assert_not_called()
        assert get_config(MLBF_TIME_CONFIG_KEY, json_value=True) == generation_time
        assert get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) == 123456

        self.statsd_incr_mock.assert_has_calls(
            [
                mock.call(f'{STATSD_PREFIX}blocked_changed', 2),
                mock.call(f'{STATSD_PREFIX}blocked_count', 1),
                mock.call(f'{STATSD_PREFIX}not_blocked_count', 3),
                mock.call('blocklist.tasks.upload_filter.upload_stash'),
                mock.call(f'{STATSD_PREFIX}success'),
            ]
        )
        self.cleanup_files_mock.assert_called_with(base_filter_id=123456)

    def test_stash_because_many_mlbf(self):
        set_config(MLBF_TIME_CONFIG_KEY, 123456, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, 987654, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '123456', 'blocked.json'
        )
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump(['madeup@guid:12345'], blocked_file)
        base_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '987654', 'blocked.json'
        )
        with storage.open(base_blocked_path, 'w') as blocked_file:
            json.dump([], blocked_file)

        upload_mlbf_to_remote_settings()

        generation_time = int(datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)

        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_called_with(
            {
                'key_format': MLBF.KEY_FORMAT,
                'stash_time': generation_time,
                'stash': {
                    'blocked': [
                        f'{self.block.guid}:'
                        f'{self.block.addon.current_version.version}'
                    ],
                    'unblocked': ['madeup@guid:12345'],
                },
            }
        )
        self.delete_mock.assert_not_called()
        assert get_config(MLBF_TIME_CONFIG_KEY, json_value=True) == generation_time
        assert get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) == 987654

        self.statsd_incr_mock.assert_has_calls(
            [
                mock.call(f'{STATSD_PREFIX}blocked_changed', 2),
                mock.call(f'{STATSD_PREFIX}blocked_count', 1),
                mock.call(f'{STATSD_PREFIX}not_blocked_count', 3),
                mock.call('blocklist.tasks.upload_filter.upload_stash'),
                mock.call(f'{STATSD_PREFIX}success'),
            ]
        )
        self.cleanup_files_mock.assert_called_with(base_filter_id=987654)

    @mock.patch.object(MLBF, 'should_reset_base_filter')
    def test_reset_base_because_over_reset_threshold(self, should_reset_mock):
        should_reset_mock.return_value = True
        set_config(MLBF_TIME_CONFIG_KEY, 123456, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, 987654, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '123456', 'blocked.json'
        )
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump(['madeup@guid:12345'], blocked_file)
        base_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, '987654', 'blocked.json'
        )
        with storage.open(base_blocked_path, 'w') as blocked_file:
            json.dump([], blocked_file)

        with self.assertNumQueries(10):
            # Mainly config gets/saves and savepoints; regression check.
            upload_mlbf_to_remote_settings()

        generation_time = int(datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000)

        self.publish_attachment_mock.assert_called_with(
            {
                'key_format': MLBF.KEY_FORMAT,
                'generation_time': generation_time,
                'attachment_type': 'bloomfilter-base',
            },
            ('filter.bin', mock.ANY, 'application/octet-stream'),
        )
        self.publish_record_mock.assert_not_called()
        self.delete_mock.assert_called_once()
        assert get_config(MLBF_TIME_CONFIG_KEY, json_value=True) == generation_time
        assert get_config(MLBF_BASE_ID_CONFIG_KEY, json_value=True) == generation_time

        gen_path = os.path.join(settings.MLBF_STORAGE_PATH, str(generation_time))
        # no stash because we're starting with a new base mlbf
        assert not os.path.exists(os.path.join(gen_path, 'stash.json'))

        self.statsd_incr_mock.assert_has_calls(
            [
                mock.call(f'{STATSD_PREFIX}blocked_changed', 2),
                mock.call(f'{STATSD_PREFIX}blocked_count', 1),
                mock.call(f'{STATSD_PREFIX}not_blocked_count', 3),
                mock.call('blocklist.tasks.upload_filter.reset_collection'),
                mock.call('blocklist.tasks.upload_filter.upload_mlbf'),
                mock.call('blocklist.tasks.upload_filter.upload_mlbf.base'),
                mock.call(f'{STATSD_PREFIX}success'),
            ]
        )

    @override_switch('blocklist_mlbf_submit', active=True)
    @mock.patch.object(MLBF, 'should_reset_base_filter')
    def test_force_base_option(self, should_reset_mock):
        should_reset_mock.return_value = False

        # set the times to now
        now = datetime.now()
        now_timestamp = now.timestamp() * 1000
        set_config(MLBF_TIME_CONFIG_KEY, now_timestamp, json_value=True)
        self.block.update(modified=now)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, str(now_timestamp), 'blocked.json'
        )
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump([f'{self.block.guid}:1.2b3'], blocked_file)
        # without force_base nothing happens
        upload_mlbf_to_remote_settings()
        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_not_called()

        # but with force_base=True we generate a filter
        upload_mlbf_to_remote_settings(force_base=True)
        self.publish_attachment_mock.assert_called_once()  # the mlbf
        self.publish_record_mock.assert_not_called()  # no stash
        self.delete_mock.assert_called()  # the collection was cleared

        # doublecheck no stash
        gen_path = os.path.join(
            settings.MLBF_STORAGE_PATH,
            str(get_config(MLBF_TIME_CONFIG_KEY, json_value=True)),
        )
        # no stash because we're starting with a new base mlbf
        assert not os.path.exists(os.path.join(gen_path, 'stash.json'))

        self.statsd_incr_mock.assert_has_calls(
            [
                mock.call(f'{STATSD_PREFIX}blocked_changed', 0),
                mock.call(f'{STATSD_PREFIX}success'),
                # 2nd execution
                mock.call(f'{STATSD_PREFIX}blocked_changed', 0),
                mock.call(f'{STATSD_PREFIX}blocked_count', 1),
                mock.call(f'{STATSD_PREFIX}not_blocked_count', 3),
                mock.call('blocklist.tasks.upload_filter.reset_collection'),
                mock.call('blocklist.tasks.upload_filter.upload_mlbf'),
                mock.call('blocklist.tasks.upload_filter.upload_mlbf.base'),
                mock.call(f'{STATSD_PREFIX}success'),
            ]
        )

    @override_switch('blocklist_mlbf_submit', active=False)
    def test_waffle_off_disables_publishing(self):
        upload_mlbf_to_remote_settings()

        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_not_called()
        assert not get_config(MLBF_TIME_CONFIG_KEY)

        # except when 'bypass_switch' kwarg is passed
        upload_mlbf_to_remote_settings(bypass_switch=True)
        self.publish_attachment_mock.assert_called()
        assert get_config(MLBF_TIME_CONFIG_KEY)

    @freeze_time('2020-01-01 12:34:56', as_arg=True)
    def test_no_block_changes(frozen_time, self):
        # This was the last time the mlbf was generated
        last_time = int((frozen_time() - timedelta(seconds=1)).timestamp() * 1000)
        # And the Block was modified just that before so would be included
        self.block.update(modified=(frozen_time() - timedelta(seconds=2)))
        set_config(MLBF_TIME_CONFIG_KEY, last_time, json_value=True)
        set_config(MLBF_BASE_ID_CONFIG_KEY, last_time, json_value=True)
        prev_blocked_path = os.path.join(
            settings.MLBF_STORAGE_PATH, str(last_time), 'blocked.json'
        )
        with storage.open(prev_blocked_path, 'w') as blocked_file:
            json.dump([f'{self.block.guid}:1.2b3'], blocked_file)

        upload_mlbf_to_remote_settings()
        # So no need for a new bloomfilter
        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_not_called()
        self.cleanup_files_mock.assert_not_called()

        # But if we add a new Block a new filter is needed
        block_factory(
            addon=addon_factory(file_kw={'is_signed': True}),
            updated_by=user_factory(),
        )
        upload_mlbf_to_remote_settings()
        self.publish_attachment_mock.assert_not_called()
        self.publish_record_mock.assert_called_once()
        self.cleanup_files_mock.assert_called_once()
        assert get_config(MLBF_TIME_CONFIG_KEY, json_value=True) == int(
            datetime(2020, 1, 1, 12, 34, 56).timestamp() * 1000
        )
        self.statsd_incr_mock.reset_mock()

        frozen_time.tick()
        # If the first block is deleted the last_modified date won't have
        # changed, but the number of blocks will, so trigger a new filter.
        last_modified = get_blocklist_last_modified_time()
        self.block.delete()
        assert last_modified == get_blocklist_last_modified_time()
        upload_mlbf_to_remote_settings()
        self.publish_attachment_mock.assert_not_called()
        assert self.publish_record_mock.call_count == 2
        assert self.cleanup_files_mock.call_count == 2

        self.statsd_incr_mock.assert_has_calls(
            [
                mock.call(f'{STATSD_PREFIX}blocked_changed', 1),
                mock.call(f'{STATSD_PREFIX}blocked_count', 1),
                mock.call(f'{STATSD_PREFIX}not_blocked_count', 4),
                mock.call('blocklist.tasks.upload_filter.upload_stash'),
                mock.call(f'{STATSD_PREFIX}success'),
            ]
        )
        self.cleanup_files_mock.assert_called_with(base_filter_id=last_time)

    @mock.patch('olympia.blocklist.cron._upload_mlbf_to_remote_settings')
    def test_no_statsd_ping_when_switch_off(self, inner_mock):
        with override_switch('blocklist_mlbf_submit', active=False):
            upload_mlbf_to_remote_settings()
            self.statsd_incr_mock.assert_not_called()

        with override_switch('blocklist_mlbf_submit', active=True):
            upload_mlbf_to_remote_settings()
            self.statsd_incr_mock.assert_called()


@pytest.mark.django_db
def test_process_blocklistsubmissions():
    user = user_factory()
    user_factory(id=settings.TASK_USER_ID)
    past_guid = 'past@'
    past_signoff_guid = 'signoff@'
    future_guid = 'future@'

    past = BlocklistSubmission.objects.create(
        input_guids=past_guid,
        updated_by=user,
        delayed_until=datetime.now() - timedelta(days=1),
        signoff_state=BlocklistSubmission.SIGNOFF_AUTOAPPROVED,
        changed_version_ids=[
            addon_factory(
                guid=past_guid,
                average_daily_users=settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
                - 1,
            ).current_version.id
        ],
    )

    past_signoff = BlocklistSubmission.objects.create(
        input_guids=past_signoff_guid,
        updated_by=user,
        delayed_until=datetime.now() - timedelta(days=1),
        signoff_state=BlocklistSubmission.SIGNOFF_APPROVED,
        signoff_by=user_factory(),
        changed_version_ids=[
            addon_factory(
                guid=past_signoff_guid,
                average_daily_users=settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
                + 1,
            ).current_version.id
        ],
    )

    future = BlocklistSubmission.objects.create(
        input_guids=future_guid,
        updated_by=user,
        delayed_until=datetime.now() + timedelta(days=1),
        signoff_state=BlocklistSubmission.SIGNOFF_AUTOAPPROVED,
        changed_version_ids=[
            addon_factory(
                guid=future_guid,
                average_daily_users=settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
                - 1,
            ).current_version.id
        ],
    )

    process_blocklistsubmissions()

    assert past.reload().signoff_state == BlocklistSubmission.SIGNOFF_PUBLISHED
    assert past_signoff.reload().signoff_state == BlocklistSubmission.SIGNOFF_PUBLISHED
    assert future.reload().signoff_state == BlocklistSubmission.SIGNOFF_AUTOAPPROVED

    assert Block.objects.filter(guid=past_guid).exists()
    assert Block.objects.filter(guid=past_signoff_guid).exists()
    assert not Block.objects.filter(guid=future_guid).exists()
