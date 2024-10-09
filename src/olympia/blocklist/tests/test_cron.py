import json
import uuid
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings

import pytest
import responses
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
    get_base_generation_time,
    get_generation_time,
    get_last_generation_time,
    process_blocklistsubmissions,
    upload_mlbf_to_remote_settings,
)
from olympia.blocklist.mlbf import MLBF
from olympia.blocklist.models import Block, BlocklistSubmission, BlockVersion
from olympia.blocklist.utils import datetime_to_ts
from olympia.constants.blocklist import MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY
from olympia.zadmin.models import set_config


STATSD_PREFIX = 'blocklist.cron.upload_mlbf_to_remote_settings.'


@freeze_time('2020-01-01 12:34:56')
@override_switch('blocklist_mlbf_submit', active=True)
class TestUploadToRemoteSettings(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.addon = addon_factory()
        self.block = block_factory(guid=self.addon.guid, updated_by=self.user)

        self.mocks: dict[str, mock.Mock] = {}
        for mock_name in (
            'olympia.blocklist.cron.statsd.incr',
            'olympia.blocklist.cron.cleanup_old_files.delay',
            'olympia.blocklist.cron.upload_filter.delay',
            'olympia.blocklist.cron.get_generation_time',
            'olympia.blocklist.cron.get_last_generation_time',
            'olympia.blocklist.cron.get_base_generation_time',
        ):
            patcher = mock.patch(mock_name)
            self.addCleanup(patcher.stop)
            self.mocks[mock_name] = patcher.start()

        self.base_time = datetime_to_ts(self.block.modified)
        self.last_time = datetime_to_ts(self.block.modified + timedelta(seconds=1))
        self.current_time = datetime_to_ts(self.block.modified + timedelta(seconds=2))
        self.mocks[
            'olympia.blocklist.cron.get_base_generation_time'
        ].return_value = self.base_time
        self.mocks[
            'olympia.blocklist.cron.get_last_generation_time'
        ].return_value = self.last_time
        self.mocks[
            'olympia.blocklist.cron.get_generation_time'
        ].return_value = self.current_time

        # Create the base/last filters by default so each test starts with a happy path
        # where there is a base/last filter with correct times that we skip the update.
        MLBF.generate_from_db(self.base_time)
        MLBF.generate_from_db(self.last_time)

    def _block_version(self, block=None, version=None, soft=False, is_signed=True):
        block = block or self.block
        version = version or version_factory(
            addon=self.addon, file_kw={'is_signed': is_signed}
        )
        return BlockVersion.objects.create(block=block, version=version, soft=soft)

    def test_skip_update_unless_force_base(self):
        """
        skip update unless force_base is true
        """
        upload_mlbf_to_remote_settings(force_base=False)

        # We skip update at this point because there is no reason to update.
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # But if we force the base filter, we update.
        upload_mlbf_to_remote_settings(force_base=True)

        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # Check that a filter was created on the second attempt
        mlbf = MLBF.load_from_storage(self.current_time)
        assert mlbf.storage.exists(mlbf.filter_path)
        assert not mlbf.storage.exists(mlbf.stash_path)

    def test_skip_update_unless_no_base_mlbf(self):
        """
        skip update unless there is no base mlbf
        """
        # We skip update at this point because there is a base filter.
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        self.mocks[
            'olympia.blocklist.cron.get_base_generation_time'
        ].return_value = None
        upload_mlbf_to_remote_settings(force_base=False)

        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

    def test_missing_last_filter_uses_base_filter(self):
        """
        When there is a base filter and no last filter,
        fallback to using the base filter
        """
        self._block_version(is_signed=True)
        # Re-created the last filter created after the new block
        MLBF.generate_from_db(self.last_time)

        # We skip the update at this point because the new last filter already
        # accounted for the new block.
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # We don't skip because the base filter is now used to compare against
        # and it has not accounted for the new block.
        self.mocks[
            'olympia.blocklist.cron.get_last_generation_time'
        ].return_value = None
        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called
        assert (
            mock.call(
                'blocklist.cron.upload_mlbf_to_remote_settings.blocked_changed', 1
            )
            in self.mocks['olympia.blocklist.cron.statsd.incr'].call_args_list
        )

    def test_skip_update_unless_recent_modified_blocks(self):
        """
        skip update unless there are recent modified blocks
        """
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # Now the last filter is older than the most recently modified block.
        older_last_time = datetime_to_ts(self.block.modified - timedelta(seconds=1))
        self.mocks[
            'olympia.blocklist.cron.get_last_generation_time'
        ].return_value = older_last_time
        MLBF.generate_from_db(older_last_time)

        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

    def test_skip_update_unless_new_blocks(self):
        """
        skip update unless there are new blocks
        """
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # Now there is a new blocked version
        self._block_version(is_signed=True)
        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

    def test_send_statsd_counts(self):
        """
        Send statsd counts for the number of blocked and not blocked items.
        """
        self._block_version(is_signed=True)
        upload_mlbf_to_remote_settings()

        statsd_calls = self.mocks['olympia.blocklist.cron.statsd.incr'].call_args_list

        assert (
            mock.call('blocklist.cron.upload_mlbf_to_remote_settings.blocked_count', 1)
            in statsd_calls
        )
        assert (
            mock.call(
                'blocklist.cron.upload_mlbf_to_remote_settings.not_blocked_count', 1
            )
            in statsd_calls
        )
        assert (
            mock.call('blocklist.cron.upload_mlbf_to_remote_settings.success')
            in statsd_calls
        )

    @override_switch('blocklist_mlbf_submit', active=False)
    def test_skip_upload_if_switch_is_disabled(self):
        upload_mlbf_to_remote_settings()
        assert not self.mocks['olympia.blocklist.cron.statsd.incr'].called
        upload_mlbf_to_remote_settings(bypass_switch=True)
        assert self.mocks['olympia.blocklist.cron.statsd.incr'].called

    def test_upload_stash_unless_force_base(self):
        """
        Upload a stash unless force_base is true. When there is a new block,
        We expect to upload a stash, unless the force_base is true, in which case
        we upload a new filter.
        """
        force_base = False
        self._block_version(is_signed=True)
        upload_mlbf_to_remote_settings(force_base=force_base)
        assert self.mocks[
            'olympia.blocklist.cron.upload_filter.delay'
        ].call_args_list == [
            mock.call(
                self.current_time,
                is_base=force_base,
            )
        ]
        mlbf = MLBF.load_from_storage(self.current_time)
        assert mlbf.storage.exists(mlbf.filter_path) == force_base
        assert mlbf.storage.exists(mlbf.stash_path) != force_base

    def test_upload_stash_unless_missing_base_filter(self):
        """
        Upload a stash unless there is no base filter.
        """
        self._block_version(is_signed=True)
        upload_mlbf_to_remote_settings()
        assert self.mocks[
            'olympia.blocklist.cron.upload_filter.delay'
        ].call_args_list == [
            mock.call(
                self.current_time,
                is_base=False,
            )
        ]
        mlbf = MLBF.load_from_storage(self.current_time)
        assert not mlbf.storage.exists(mlbf.filter_path)
        assert mlbf.storage.exists(mlbf.stash_path)

        self.mocks[
            'olympia.blocklist.cron.get_base_generation_time'
        ].return_value = None
        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                is_base=True,
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        assert mlbf.storage.exists(mlbf.filter_path)

    @mock.patch('olympia.blocklist.cron.BASE_REPLACE_THRESHOLD', 1)
    def test_upload_stash_unless_enough_changes(self):
        """
        When there are new blocks, upload either a stash or a filter depending on
        whether we have surpased the BASE_REPLACE_THRESHOLD amount.
        """
        self._block_version(is_signed=True)
        upload_mlbf_to_remote_settings()
        assert self.mocks[
            'olympia.blocklist.cron.upload_filter.delay'
        ].call_args_list == [
            mock.call(
                self.current_time,
                is_base=False,
            )
        ]
        mlbf = MLBF.load_from_storage(self.current_time)
        assert not mlbf.storage.exists(mlbf.filter_path)
        assert mlbf.storage.exists(mlbf.stash_path)

        self._block_version(is_signed=True)
        # Create a new current time so we can test that the stash is not created
        self.current_time = datetime_to_ts(self.block.modified + timedelta(seconds=4))
        self.mocks[
            'olympia.blocklist.cron.get_generation_time'
        ].return_value = self.current_time
        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                is_base=True,
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        new_mlbf = MLBF.load_from_storage(self.current_time)
        assert new_mlbf.storage.exists(new_mlbf.filter_path)
        assert not new_mlbf.storage.exists(new_mlbf.stash_path)

    def test_cleanup_old_files(self):
        """
        Cleanup old files only if a base filter already exists.
        """
        upload_mlbf_to_remote_settings(force_base=True)
        assert self.mocks[
            'olympia.blocklist.cron.cleanup_old_files.delay'
        ].call_args_list == [mock.call(base_filter_id=self.base_time)]

        self.mocks[
            'olympia.blocklist.cron.get_base_generation_time'
        ].return_value = None
        upload_mlbf_to_remote_settings(force_base=True)
        assert (
            self.mocks['olympia.blocklist.cron.cleanup_old_files.delay'].call_count == 1
        )

    def test_raises_if_base_generation_time_invalid(self):
        """
        When a base_generation_time is provided, but no filter exists for it,
        raise no filter found.
        """
        self.mocks['olympia.blocklist.cron.get_base_generation_time'].return_value = 1
        with pytest.raises(FileNotFoundError):
            upload_mlbf_to_remote_settings(force_base=True)

    def test_raises_if_last_generation_time_invalid(self):
        """
        When a last_generation_time is provided, but no filter exists for it,
        raise no filter found.
        """
        self.mocks['olympia.blocklist.cron.get_last_generation_time'].return_value = 1
        with pytest.raises(FileNotFoundError):
            upload_mlbf_to_remote_settings(force_base=True)


class TestTimeMethods(TestCase):
    @freeze_time('2024-10-10 12:34:56')
    def test_get_generation_time(self):
        assert get_generation_time() == datetime_to_ts()
        assert isinstance(get_generation_time(), int)

    def test_get_last_generation_time(self):
        assert get_last_generation_time() is None
        set_config(MLBF_TIME_CONFIG_KEY, 1)
        assert get_last_generation_time() == 1

    def test_get_base_generation_time(self):
        assert get_base_generation_time() is None
        set_config(MLBF_BASE_ID_CONFIG_KEY, 1)
        assert get_base_generation_time() == 1


@pytest.mark.django_db
def test_process_blocklistsubmissions():
    user = user_factory()
    user_factory(id=settings.TASK_USER_ID)
    past_guid = 'past@'
    past_signoff_guid = 'signoff@'
    future_guid = 'future@'
    responses.add_callback(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
    )

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
