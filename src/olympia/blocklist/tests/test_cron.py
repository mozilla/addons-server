import json
import uuid
from datetime import datetime, timedelta
from typing import List
from unittest import mock

from django.conf import settings

import pytest
import responses
import time_machine
from waffle.testutils import override_switch

from olympia import amo
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
from olympia.blocklist.models import Block, BlocklistSubmission, BlockType, BlockVersion
from olympia.blocklist.tasks import upload_filter
from olympia.blocklist.utils import datetime_to_ts, get_mlbf_base_id_config_key
from olympia.constants.blocklist import BlockListAction
from olympia.zadmin.models import set_config


STATSD_PREFIX = 'blocklist.cron.upload_mlbf_to_remote_settings.'


@time_machine.travel('2020-01-01 12:34:56', tick=False)
@override_switch('blocklist_mlbf_submit', active=True)
class TestUploadToRemoteSettings(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.addon = addon_factory()
        self.block = block_factory(guid=self.addon.guid, updated_by=self.user)

        self.mocks: dict[str, mock.Mock] = {}
        for mock_name in (
            'olympia.blocklist.cron.statsd.incr',
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
        self.mocks['olympia.blocklist.cron.get_base_generation_time'].side_effect = (
            lambda _block_type: self.base_time
        )
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

    def _block_version(
        self, block=None, version=None, block_type=BlockType.BLOCKED, is_signed=True
    ):
        block = block or self.block
        version = version or version_factory(
            addon=self.addon, file_kw={'is_signed': is_signed}
        )
        return BlockVersion.objects.create(
            block=block, version=version, block_type=block_type
        )

    def test_skip_update_unless_no_base_mlbf(self):
        """
        skip update unless there is no base mlbf for the given block type
        """
        # We skip update at this point because there is a base filter.
        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0

        # Delete the base filter so we can test again with different conditions
        self.mocks['olympia.blocklist.cron.get_base_generation_time'].side_effect = (
            lambda _block_type: None
        )

        upload_mlbf_to_remote_settings(force_base=False)

        # Now that the base filter is missing, we expect to upload a new filter
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                    BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                    BlockListAction.CLEAR_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_missing_last_filter_uses_base_filter(self):
        """
        When there is a base filter and no last filter,
        fallback to using the base filter for comparing stashes.
        """
        block_version = self._block_version(is_signed=True)
        # Re-create the last filter so we ensure
        # the block is already processed comparing to previous
        MLBF.generate_from_db(self.last_time)

        # Ensure the block was created before the last filter
        assert datetime_to_ts(block_version.modified) < self.last_time
        # We skip the update at this point because the block is already accounted for
        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0

        # We don't skip because the base filter is now used to compare against
        # and it has not accounted for the new block.
        self.mocks[
            'olympia.blocklist.cron.get_last_generation_time'
        ].return_value = None
        upload_mlbf_to_remote_settings(force_base=False)
        # We expect to upload a stash because the block is not accounted for in the base
        # filter and the last filter is missing.
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_skip_update_if_unsigned_blocks_added(self):
        """
        skip update if there are only unsigned new blocks
        """
        for block_type in BlockType:
            self._block_version(block_type=block_type, is_signed=False)

        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0

    def test_skip_update_when_there_are_no_new_blocks(self):
        """
        If there are no new blocks, and we are not forcing a base update,
        then it is a no-op.
        """
        upload_mlbf_to_remote_settings(force_base=False)

        assert MLBF.load_from_storage(self.current_time) is None
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0

    def test_send_statsd_counts(self):
        """
        Send statsd counts for the number of blocked,
        soft blocked, and not blocked items.
        """
        self._block_version(block_type=BlockType.BLOCKED)
        self._block_version(block_type=BlockType.SOFT_BLOCKED)
        upload_mlbf_to_remote_settings()

        statsd_calls = self.mocks['olympia.blocklist.cron.statsd.incr'].call_args_list

        assert (
            mock.call('blocklist.cron.upload_mlbf_to_remote_settings.blocked_count', 1)
            in statsd_calls
        )
        assert (
            mock.call(
                'blocklist.cron.upload_mlbf_to_remote_settings.soft_blocked_count', 1
            )
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
        assert self.mocks['olympia.blocklist.cron.statsd.incr'].call_count == 0
        upload_mlbf_to_remote_settings(bypass_switch=True)
        assert self.mocks['olympia.blocklist.cron.statsd.incr'].call_count == 1

    def test_upload_stash_unless_force_base(self):
        """
        Upload a stash unless force_base is true. When there is a new block,
        We expect to upload a stash, unless the force_base is true, in which case
        we upload a new filter.
        """
        # First we run without any new blocks
        upload_mlbf_to_remote_settings(force_base=False)

        assert MLBF.load_from_storage(self.current_time) is None
        # Are not uploading anything because there are no changes
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0

        # Create a new blocked version for each block type
        for block_type in BlockType:
            self._block_version(block_type=block_type)

        # Now we run again with the new blocks
        upload_mlbf_to_remote_settings(force_base=False)

        mlbf = MLBF.load_from_storage(self.current_time)

        # Expect a stash because there is a new hard block and force_base is False
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        assert mlbf.storage.exists(mlbf.stash_path)

        for block_type in BlockType:
            assert not mlbf.storage.exists(mlbf.filter_path(block_type))

        # Delete the MLBF so we can test again with different conditions
        mlbf.delete()

        upload_mlbf_to_remote_settings(force_base=True)

        # Now expect a new filter because force_base is True
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                    BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                    BlockListAction.CLEAR_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    @mock.patch('olympia.blocklist.mlbf.get_base_replace_threshold')
    def test_upload_stash_unless_enough_changes(self, mock_get_base_replace_threshold):
        """
        When there are new blocks, upload a stash unless
        we have surpased the threshold amount.
        """
        mock_get_base_replace_threshold.return_value = 1

        for block_type in BlockType:
            self._block_version(is_signed=True, block_type=block_type)

        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        mlbf = MLBF.load_from_storage(self.current_time)
        for block_type in BlockType:
            assert not mlbf.storage.exists(mlbf.filter_path(block_type))
        assert mlbf.storage.exists(mlbf.stash_path)

        # delete the mlbf so we can test again with different conditions
        mlbf.delete()

        # Create another blocked version to exceed the threshold
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)

        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                    BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                    BlockListAction.CLEAR_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        new_mlbf = MLBF.load_from_storage(self.current_time)

        for block_type in BlockType:
            assert new_mlbf.storage.exists(new_mlbf.filter_path(block_type))

        assert not new_mlbf.storage.exists(new_mlbf.stash_path)

    def _test_upload_stash_and_filter(
        self,
        expected_actions: List[BlockListAction],
    ):
        set_config(amo.config_keys.BLOCKLIST_BASE_REPLACE_THRESHOLD, 1)
        upload_mlbf_to_remote_settings()

        # Generation time is set to current time so we can load the MLBF.
        mlbf = MLBF.load_from_storage(self.current_time)

        if BlockListAction.UPLOAD_BLOCKED_FILTER.name in expected_actions:
            assert mlbf.storage.exists(mlbf.filter_path(BlockType.BLOCKED)), (
                'Expected filter {BlockType.BLOCKED} but none exists'
            )

        if BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name in expected_actions:
            assert mlbf.storage.exists(mlbf.filter_path(BlockType.SOFT_BLOCKED)), (
                'Expected filter {BlockType.SOFT_BLOCKED} but none exists'
            )

        if BlockListAction.UPLOAD_STASH.name in expected_actions:
            assert mlbf.storage.exists(mlbf.stash_path), (
                'Expected stash but none exists'
            )

        assert (
            mock.call(
                self.current_time,
                actions=expected_actions,
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_upload_blocked_stash_and_softblock_filter(self):
        """
        When there are enough blocked versions for a stash, and enough soft blocked
        version for a filter, then if soft blocking is disabled, we expect a stash
        and if it is enabled we expect both filters to be uploaded.
        """
        # Enough blocks for a stash
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        # Enough soft blocks for a filter
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)

        self._test_upload_stash_and_filter(
            [
                BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                BlockListAction.CLEAR_STASH.name,
            ]
        )

    def test_upload_soft_blocked_stash_and_blocked_filter(self):
        """
        When there are enough soft blocks for a stash, and enough blocks for a filter,
        Then we always upload a new filter,
        regardless if softblocking is enabled or not.
        """
        # Enough soft blocks for a stash
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)
        # Enough blocked versions for a filter
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)

        self._test_upload_stash_and_filter(
            [
                BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                BlockListAction.CLEAR_STASH.name,
            ]
        )

    def test_upload_blocked_and_softblocked_filter(self):
        """
        When there are enough blocked and soft blocked versions for a filter,
        then we expect to upload both filters.
        """
        # Enough blocked versions for a filter
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        # Enough soft blocks for a filter
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)

        self._test_upload_stash_and_filter(
            [
                BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                BlockListAction.CLEAR_STASH.name,
            ]
        )

    def test_upload_blocked_and_softblocked_stash(self):
        """
        When there are enough blocked and soft blocked versions for a stash,
        then we expect to upload a new stash.
        """
        # Enough blocked versions for a stash
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        # Enough soft blocks for a stash
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)

        self._test_upload_stash_and_filter(
            [
                BlockListAction.UPLOAD_STASH.name,
            ]
        )

    def test_remove_storage_if_no_update(self):
        """
        If there is no update, remove the storage used by the current mlbf.
        """
        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0
        assert MLBF.load_from_storage(self.current_time) is None

    def test_creates_base_filter_if_base_generation_time_invalid(self):
        """
        When a base_generation_time is provided, but no filter exists for it,
        then we create a new filter.
        """
        self.mocks['olympia.blocklist.cron.get_base_generation_time'].return_value = 1
        upload_mlbf_to_remote_settings(force_base=True)
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                    BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                    BlockListAction.CLEAR_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_compares_against_base_filter_if_missing_previous_filter(self):
        """
        When no previous filter is found, compare blocks against the base filter
        of that block type.
        """
        blocked_version = self._block_version(block_type=BlockType.BLOCKED)
        MLBF.generate_from_db(self.last_time)

        # The block is created at the same time as the base filter
        # but before the last filter
        assert datetime_to_ts(blocked_version.modified) == self.base_time
        assert datetime_to_ts(blocked_version.modified) < self.last_time

        upload_mlbf_to_remote_settings(force_base=False)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_count == 0

        # Delete the last filter, now the base filter will be used to compare
        MLBF.load_from_storage(self.last_time).delete()
        upload_mlbf_to_remote_settings(force_base=False)
        # We expect to not upload anything as the hard block has already been
        # accounted for in the base filter.
        assert (
            mock.call(
                self.current_time,
                actions=[BlockListAction.UPLOAD_STASH.name],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def _test_dont_skip_update_if_all_blocked_or_not_blocked(
        self, block_type: BlockType
    ):
        """
        If all versions are either blocked or not blocked, don't skip the update.
        """
        for _ in range(0, 10):
            self._block_version(block_type=block_type)

        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                actions=[
                    BlockListAction.UPLOAD_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_dont_skip_update_if_all_blocked_or_not_blocked_for_soft_blocked(self):
        self._test_dont_skip_update_if_all_blocked_or_not_blocked(
            block_type=BlockType.SOFT_BLOCKED
        )

    def test_dont_skip_update_if_all_blocked_or_not_blocked_for_blocked(self):
        self._test_dont_skip_update_if_all_blocked_or_not_blocked(
            block_type=BlockType.BLOCKED
        )

    def test_invalid_cache_results_in_diff(self):
        self._block_version(block_type=BlockType.BLOCKED)

        # First we create the current filter including the blocked version
        upload_mlbf_to_remote_settings()

        base_mlbf = MLBF.load_from_storage(self.current_time)

        # Remove the blocked version from the cache.json file so we can test that
        # the next generation includes the blocked version.
        with base_mlbf.storage.open(base_mlbf.data._cache_path, 'r+') as f:
            data = json.load(f)
            del data['blocked']
            f.seek(0)
            json.dump(data, f)
            f.truncate()

        # Set the generation time to after the current time so we can test that the
        # diff includes the blocked version after it is removed from the cache.json
        next_time = self.current_time + 1
        self.mocks[
            'olympia.blocklist.cron.get_generation_time'
        ].return_value = next_time
        upload_mlbf_to_remote_settings()

        # We expect to upload a stash because the cache.json we are comparing against
        # is missing the blocked version.
        assert (
            mock.call(
                next_time,
                actions=[
                    BlockListAction.UPLOAD_STASH.name,
                ],
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_pass_correct_arguments_to_upload_filter(self):
        self.mocks['olympia.blocklist.cron.upload_filter.delay'].stop()
        with mock.patch(
            'olympia.blocklist.cron.upload_filter.delay', wraps=upload_filter.delay
        ) as spy_delay:
            upload_mlbf_to_remote_settings(force_base=True)
            assert (
                mock.call(
                    self.current_time,
                    actions=[
                        BlockListAction.UPLOAD_BLOCKED_FILTER.name,
                        BlockListAction.UPLOAD_SOFT_BLOCKED_FILTER.name,
                        BlockListAction.CLEAR_STASH.name,
                    ],
                )
                in spy_delay.call_args_list
            )


class TestTimeMethods(TestCase):
    @time_machine.travel('2024-10-10 12:34:56', tick=False)
    def test_get_generation_time(self):
        assert get_generation_time() == datetime_to_ts()
        assert isinstance(get_generation_time(), int)

    def test_get_last_generation_time(self):
        assert get_last_generation_time() is None
        set_config(amo.config_keys.BLOCKLIST_MLBF_TIME, 1)
        assert get_last_generation_time() == 1

    def test_get_base_generation_time(self):
        for block_type in BlockType:
            assert get_base_generation_time(block_type) is None
            set_config(get_mlbf_base_id_config_key(block_type, compat=True), 123)
            assert get_base_generation_time(block_type) == 123


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
        signoff_state=BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED,
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
        signoff_state=BlocklistSubmission.SIGNOFF_STATES.APPROVED,
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
        signoff_state=BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED,
        changed_version_ids=[
            addon_factory(
                guid=future_guid,
                average_daily_users=settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD
                - 1,
            ).current_version.id
        ],
    )

    process_blocklistsubmissions()

    assert past.reload().signoff_state == BlocklistSubmission.SIGNOFF_STATES.PUBLISHED
    assert (
        past_signoff.reload().signoff_state
        == BlocklistSubmission.SIGNOFF_STATES.PUBLISHED
    )
    assert (
        future.reload().signoff_state == BlocklistSubmission.SIGNOFF_STATES.AUTOAPPROVED
    )

    assert Block.objects.filter(guid=past_guid).exists()
    assert Block.objects.filter(guid=past_signoff_guid).exists()
    assert not Block.objects.filter(guid=future_guid).exists()
