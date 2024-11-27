import json
import uuid
from datetime import datetime, timedelta
from typing import List, Union
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
from olympia.blocklist.models import Block, BlocklistSubmission, BlockType, BlockVersion
from olympia.blocklist.tasks import upload_filter
from olympia.blocklist.utils import datetime_to_ts
from olympia.constants.blocklist import MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY
from olympia.zadmin.models import set_config


STATSD_PREFIX = 'blocklist.cron.upload_mlbf_to_remote_settings.'


@freeze_time('2020-01-01 12:34:56')
@override_switch('blocklist_mlbf_submit', active=True)
@override_switch('enable-soft-blocking', active=False)
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

    def _test_skip_update_unless_force_base(self, enable_soft_blocking=False):
        """
        skip update unless force_base is true
        """
        # We skip update at this point because there is no reason to update.
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        filter_list = [BlockType.BLOCKED.name]

        if enable_soft_blocking:
            filter_list.append(BlockType.SOFT_BLOCKED.name)

        with override_switch('enable-soft-blocking', active=enable_soft_blocking):
            upload_mlbf_to_remote_settings(force_base=True)

            assert (
                mock.call(
                    self.current_time,
                    filter_list=filter_list,
                    create_stash=False,
                )
            ) in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list

            # Check that both filters were created on the second attempt
            mlbf = MLBF.load_from_storage(self.current_time)
            self.assertTrue(
                mlbf.storage.exists(mlbf.filter_path(BlockType.BLOCKED)),
            )
            self.assertEqual(
                mlbf.storage.exists(mlbf.filter_path(BlockType.SOFT_BLOCKED)),
                enable_soft_blocking,
            )
            assert not mlbf.storage.exists(mlbf.stash_path)

    def test_skip_update_unless_forced_soft_blocking_disabled(self):
        self._test_skip_update_unless_force_base(enable_soft_blocking=False)

    def test_skip_update_unless_forced_soft_blocking_enabled(self):
        self._test_skip_update_unless_force_base(enable_soft_blocking=True)

    def _test_skip_update_unless_no_base_mlbf(
        self, block_type: BlockType, filter_list: Union[List[BlockType], None] = None
    ):
        """
        skip update unless there is no base mlbf for the given block type
        """
        # We skip update at this point because there is a base filter.
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        self.mocks['olympia.blocklist.cron.get_base_generation_time'].side_effect = (
            lambda _block_type: None if _block_type == block_type else self.base_time
        )
        upload_mlbf_to_remote_settings(force_base=False)

        if filter_list is None:
            assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called
        else:
            assert (
                mock.call(
                    self.current_time,
                    filter_list=filter_list,
                    create_stash=False,
                )
            ) in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list

    def test_skip_update_unless_no_base_mlbf_for_blocked(self):
        self._test_skip_update_unless_no_base_mlbf(
            BlockType.BLOCKED, filter_list=[BlockType.BLOCKED.name]
        )

    @override_switch('enable-soft-blocking', active=True)
    def test_skip_update_unless_no_base_mlbf_for_soft_blocked_with_switch_enabled(self):
        self._test_skip_update_unless_no_base_mlbf(
            BlockType.SOFT_BLOCKED, filter_list=[BlockType.SOFT_BLOCKED.name]
        )

    def test_skip_update_unless_no_base_mlbf_for_soft_blocked_with_switch_disabled(
        self,
    ):
        self._test_skip_update_unless_no_base_mlbf(
            BlockType.SOFT_BLOCKED, filter_list=None
        )

    def test_missing_last_filter_uses_base_filter(self):
        """
        When there is a base filter and no last filter,
        fallback to using the base filter
        """
        block_version = self._block_version(is_signed=True)
        # Re-create the last filter so we ensure
        # the block is already processed comparing to previous
        MLBF.generate_from_db(self.last_time)

        assert datetime_to_ts(block_version.modified) < self.last_time
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
        assert (
            mock.call(
                self.current_time,
                filter_list=[],
                create_stash=True,
            )
        ) in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list

    @override_switch('enable-soft-blocking', active=True)
    def test_skip_update_if_unsigned_blocks_added(self):
        """
        skip update if there are only unsigned new blocks
        """
        self._block_version(block_type=BlockType.BLOCKED, is_signed=False)
        self._block_version(block_type=BlockType.SOFT_BLOCKED, is_signed=False)

        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

    def _test_skip_update_unless_new_blocks(
        self, block_type: BlockType, enable_soft_blocking=False, expect_update=False
    ):
        """
        skip update unless there are new blocks
        """
        with override_switch('enable-soft-blocking', active=enable_soft_blocking):
            upload_mlbf_to_remote_settings(force_base=False)
            assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

            # Now there is a new blocked version
            self._block_version(block_type=block_type, is_signed=True)
            upload_mlbf_to_remote_settings(force_base=False)

            self.assertEqual(
                expect_update,
                self.mocks['olympia.blocklist.cron.upload_filter.delay'].called,
            )

    def test_skip_update_unless_new_blocks_for_blocked(self):
        self._test_skip_update_unless_new_blocks(
            block_type=BlockType.BLOCKED,
            expect_update=True,
        )

    def test_skip_update_unless_new_blocks_for_soft_blocked_with_switch_disabled(self):
        self._test_skip_update_unless_new_blocks(
            block_type=BlockType.SOFT_BLOCKED,
            enable_soft_blocking=False,
            expect_update=False,
        )

    def test_skip_update_unless_new_blocks_for_soft_blocked_with_switch_enabled(self):
        self._test_skip_update_unless_new_blocks(
            block_type=BlockType.SOFT_BLOCKED,
            enable_soft_blocking=True,
            expect_update=True,
        )

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
        assert not self.mocks['olympia.blocklist.cron.statsd.incr'].called
        upload_mlbf_to_remote_settings(bypass_switch=True)
        assert self.mocks['olympia.blocklist.cron.statsd.incr'].called

    def _test_upload_stash_unless_force_base(
        self,
        block_types: List[BlockType],
        expect_stash: bool,
        filter_list: Union[List[BlockType], None],
        enable_soft_blocking: bool,
    ):
        """
        Upload a stash unless force_base is true. When there is a new block,
        We expect to upload a stash, unless the force_base is true, in which case
        we upload a new filter.
        """
        for block_type in block_types:
            self._block_version(block_type=block_type)

        with override_switch('enable-soft-blocking', active=enable_soft_blocking):
            upload_mlbf_to_remote_settings(force_base=False)

            self.assertEqual(
                expect_stash,
                mock.call(
                    self.current_time,
                    filter_list=[],
                    create_stash=True,
                )
                in self.mocks[
                    'olympia.blocklist.cron.upload_filter.delay'
                ].call_args_list,
            )

            mlbf = MLBF.load_from_storage(self.current_time)

            if expect_stash:
                assert mlbf.storage.exists(mlbf.stash_path)

                for block_type in BlockType:
                    assert not mlbf.storage.exists(mlbf.filter_path(block_type))
            else:
                assert mlbf is None

            upload_mlbf_to_remote_settings(force_base=True)
            next_mlbf = MLBF.load_from_storage(self.current_time)
            expected_block_types = []

            for block_type in filter_list:
                assert next_mlbf.storage.exists(next_mlbf.filter_path(block_type))
                expected_block_types.append(block_type.name)

            assert (
                mock.call(
                    self.current_time,
                    filter_list=expected_block_types,
                    create_stash=False,
                )
                in self.mocks[
                    'olympia.blocklist.cron.upload_filter.delay'
                ].call_args_list
            )

    def test_upload_stash_unless_force_base_for_blocked_with_switch_disabled(self):
        """
        When force base is false, it uploads a stash because there is a new hard blocked
        version. When force base is true, it uploads the blocked filter for the same
        reason.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[BlockType.BLOCKED],
            expect_stash=True,
            filter_list=[BlockType.BLOCKED],
            enable_soft_blocking=False,
        )

    def test_upload_stash_unless_force_base_for_blocked_with_switch_enabled(self):
        """
        When force base is false, it uploads a stash because soft block is enabled
        and there is a new hard blocked version. When force base is true, it uploads
        both blocked and soft blocked filters for the previous reason and because
        soft blocking is enabled.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[BlockType.BLOCKED],
            expect_stash=True,
            filter_list=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
            enable_soft_blocking=True,
        )

    def test_upload_stash_unless_force_base_for_soft_blocked_with_switch_disabled(self):
        """
        When force base is false, it does not upload a stash even when there is a new
        soft blocked version, because soft blocking is disabled.
        When force base is true, it uploads only the blocked filter
        for the same reason.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[BlockType.SOFT_BLOCKED],
            expect_stash=False,
            filter_list=[BlockType.BLOCKED],
            enable_soft_blocking=False,
        )

    def test_upload_stash_unless_force_base_for_soft_blocked_with_switch_enabled(self):
        """
        When force base is false, it uploads a stash because soft block is enabled
        and there is a new soft blocked version. When force base is true, it uploads
        both blocked and soft blocked filters.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[BlockType.SOFT_BLOCKED],
            expect_stash=True,
            filter_list=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
            enable_soft_blocking=True,
        )

    def test_upload_stash_unless_force_base_for_both_blocked_with_switch_disabled(self):
        """
        When force base is false, it uploads a stash even though soft blocking disabled
        because there is a hard blocked version. When force base is true,
        it uploads only the blocked filter for the same reason.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
            expect_stash=True,
            filter_list=[BlockType.BLOCKED],
            enable_soft_blocking=False,
        )

    def test_upload_stash_unless_force_base_for_both_blocked_with_switch_enabled(self):
        """
        When force base is false, it uploads a stash because there are new hard and soft
        blocked versions. When force base is true,
        it uploads both blocked + soft blocked filters for the same reason.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
            expect_stash=True,
            filter_list=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
            enable_soft_blocking=True,
        )

    def test_dont_upload_stash_unless_force_base_for_both_blocked_with_switch_enabled(
        self,
    ):
        """
        When force base is false, it does not upload a stash because
        there are no new versions.When force base is true,
        it uploads both blocked and soft blocked filters because
        soft blocking is enabled.
        """
        self._test_upload_stash_unless_force_base(
            block_types=[],
            expect_stash=False,
            filter_list=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
            enable_soft_blocking=True,
        )

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
                filter_list=[],
                create_stash=True,
            )
        ]
        mlbf = MLBF.load_from_storage(self.current_time)
        assert not mlbf.storage.exists(mlbf.filter_path(BlockType.BLOCKED))
        assert not mlbf.storage.exists(mlbf.filter_path(BlockType.SOFT_BLOCKED))
        assert mlbf.storage.exists(mlbf.stash_path)

        self.mocks['olympia.blocklist.cron.get_base_generation_time'].side_effect = (
            lambda _block_type: None
        )
        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                filter_list=[BlockType.BLOCKED.name],
                create_stash=False,
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        assert mlbf.storage.exists(mlbf.filter_path(BlockType.BLOCKED))

        with override_switch('enable-soft-blocking', active=True):
            upload_mlbf_to_remote_settings()
            assert mlbf.storage.exists(mlbf.filter_path(BlockType.SOFT_BLOCKED))
            assert (
                mock.call(
                    self.current_time,
                    filter_list=[BlockType.BLOCKED.name, BlockType.SOFT_BLOCKED.name],
                    create_stash=False,
                )
            ) in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list

    @mock.patch('olympia.blocklist.mlbf.BASE_REPLACE_THRESHOLD', 1)
    @override_switch('enable-soft-blocking', active=True)
    def test_upload_stash_unless_enough_changes(self):
        block_type = BlockType.BLOCKED
        """
        When there are new blocks, upload either a stash or a filter depending on
        whether we have surpased the BASE_REPLACE_THRESHOLD amount.
        """
        for _block_type in BlockType:
            self._block_version(is_signed=True, block_type=_block_type)

        upload_mlbf_to_remote_settings()
        assert self.mocks[
            'olympia.blocklist.cron.upload_filter.delay'
        ].call_args_list == [
            mock.call(
                self.current_time,
                filter_list=[],
                create_stash=True,
            )
        ]
        mlbf = MLBF.load_from_storage(self.current_time)
        assert not mlbf.storage.exists(mlbf.filter_path(block_type))
        assert mlbf.storage.exists(mlbf.stash_path)

        # delete the mlbf so we can test again with different conditions
        mlbf.delete()

        self._block_version(is_signed=True, block_type=block_type)

        upload_mlbf_to_remote_settings()
        assert (
            mock.call(
                self.current_time,
                filter_list=[block_type.name],
                create_stash=True,
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )
        new_mlbf = MLBF.load_from_storage(self.current_time)
        assert new_mlbf.storage.exists(new_mlbf.filter_path(block_type))
        assert new_mlbf.storage.exists(new_mlbf.stash_path)
        with new_mlbf.storage.open(new_mlbf.stash_path, 'r') as f:
            data = json.load(f)
            # We expect an empty list for hard blocks because we are
            # uploading a new hard filter.
            assert len(data['blocked']) == 0
            # We can still see there are 2 hard blocked versions in the new filter.
            assert len(new_mlbf.data.blocked_items) == 2
            assert len(data['softblocked']) == 1

    @mock.patch('olympia.blocklist.mlbf.BASE_REPLACE_THRESHOLD', 1)
    def _test_upload_stash_and_filter(
        self,
        enable_soft_blocking: bool,
        expected_stash: dict | None,
        expected_filters: List[BlockType],
    ):
        with override_switch('enable-soft-blocking', active=enable_soft_blocking):
            upload_mlbf_to_remote_settings()

        # Generation time is set to current time so we can load the MLBF.
        mlbf = MLBF.load_from_storage(self.current_time)

        if expected_stash is None:
            assert not mlbf.storage.exists(
                mlbf.stash_path
            ), 'Expected no stash but one exists'
        else:
            assert mlbf.storage.exists(
                mlbf.stash_path
            ), f'Expected stash {expected_stash} but none exists'
            with mlbf.storage.open(mlbf.stash_path, 'r') as f:
                data = json.load(f)
                for key, expected_count in expected_stash.items():
                    assert (
                        len(data[key]) == expected_count
                    ), f'Expected {expected_count} {key} but got {len(data[key])}'

        for expected_filter in expected_filters:
            assert mlbf.storage.exists(
                mlbf.filter_path(expected_filter)
            ), f'Expected filter {expected_filter} but none exists'

    def test_upload_blocked_stash_and_softblock_filter(self):
        # Enough blocks for a stash
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        # Enough soft blocks for a filter
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)

        # Expected stash does not change
        expected_stash = {
            'blocked': 1,
            # Expect no soft blocks because there are enough for a filter.
            'softblocked': 0,
            # There are no unblocked versions
            'unblocked': 0,
        }

        self._test_upload_stash_and_filter(
            # Even though there are enough soft blocks, soft blocking is disabled
            enable_soft_blocking=False,
            expected_stash=expected_stash,
            # Expect no filter as soft blocking is disabled
            expected_filters=[],
        )

        # Now try again with soft blocking enabled
        self._test_upload_stash_and_filter(
            # Soft blocking is enabled, so we expect the same stash and a new filter
            enable_soft_blocking=True,
            expected_stash=expected_stash,
            # Expect a soft blocked filter
            expected_filters=[BlockType.SOFT_BLOCKED],
        )

    def test_upload_soft_blocked_stash_and_blocked_filter(self):
        # Enough soft blocks for a stash
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)
        # Enough blocked versions for a filter
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)

        self._test_upload_stash_and_filter(
            enable_soft_blocking=False,
            # Expect no stash because there are enough blocked versions for a filter
            # and soft blocking is disabled
            expected_stash=None,
            # Expect a blocked filter
            expected_filters=[BlockType.BLOCKED],
        )

        # Now try again with soft blocking enabled
        self._test_upload_stash_and_filter(
            enable_soft_blocking=True,
            # Expect a stash and a blocked filter
            expected_stash={
                # Expect no blocked versions because there are enough for a filter
                'blocked': 0,
                # Expect a soft blocked version when there is one
                # and soft blocking is enabled
                'softblocked': 1,
                # There are no unblocked versions
                'unblocked': 0,
            },
            # Expect a blocked filter
            expected_filters=[BlockType.BLOCKED],
        )

    def test_upload_blocked_and_softblocked_filter(self):
        # Enough blocked versions for a filter
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        # Enough soft blocks for a filter
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)

        self._test_upload_stash_and_filter(
            enable_soft_blocking=False,
            expected_stash=None,
            expected_filters=[BlockType.BLOCKED],
        )

        # Now try again with soft blocking enabled
        self._test_upload_stash_and_filter(
            enable_soft_blocking=True,
            expected_stash=None,
            expected_filters=[BlockType.BLOCKED, BlockType.SOFT_BLOCKED],
        )

    def test_upload_blocked_and_softblocked_stash(self):
        # Enough blocked versions for a stash
        self._block_version(is_signed=True, block_type=BlockType.BLOCKED)
        # Enough soft blocks for a stash
        self._block_version(is_signed=True, block_type=BlockType.SOFT_BLOCKED)

        self._test_upload_stash_and_filter(
            enable_soft_blocking=False,
            expected_stash={
                # Expect a blocked version
                'blocked': 1,
                # Expect no soft blocks because soft blocking is disabled
                'softblocked': 0,
                # There are no unblocked versions
                'unblocked': 0,
            },
            expected_filters=[],
        )

        # Now try again with soft blocking enabled
        self._test_upload_stash_and_filter(
            enable_soft_blocking=True,
            expected_stash={
                # We still have the blocked version
                'blocked': 1,
                # Expect a soft blocked version because there is one
                # and soft blocking is enabled
                'softblocked': 1,
                # There are no unblocked versions
                'unblocked': 0,
            },
            expected_filters=[],
        )

    def test_remove_storage_if_no_update(self):
        """
        If there is no update, remove the storage used by the current mlbf.
        """
        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called
        assert MLBF.load_from_storage(self.current_time) is None

    def test_creates_base_filter_if_base_generation_time_invalid(self):
        """
        When a base_generation_time is provided, but no filter exists for it,
        raise no filter found.
        """
        self.mocks['olympia.blocklist.cron.get_base_generation_time'].return_value = 1
        upload_mlbf_to_remote_settings(force_base=True)
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

    def test_compares_against_base_filter_if_missing_previous_filter(self):
        """
        When no previous filter is found, compare blocks against the base filter
        of that block type.
        """
        # Hard block version is accounted for in the base filter
        self._block_version(block_type=BlockType.BLOCKED)
        MLBF.generate_from_db(self.base_time)
        # Soft block version is not accounted for in the base filter
        # but accounted for in the last filter
        self._block_version(block_type=BlockType.SOFT_BLOCKED)
        MLBF.generate_from_db(self.last_time)

        upload_mlbf_to_remote_settings(force_base=False)
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # Delete the last filter, now the base filter will be used to compare
        MLBF.load_from_storage(self.last_time).delete()
        upload_mlbf_to_remote_settings(force_base=False)
        # We expect to not upload anything as soft blocking is disabled
        # and only the soft blocked version is missing from the base filter
        assert not self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

        # now with softblocking enabled we can account for the soft blocked version
        with override_switch('enable-soft-blocking', active=True):
            upload_mlbf_to_remote_settings(force_base=False)
            assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

    @override_switch('enable-soft-blocking', active=True)
    def _test_dont_skip_update_if_all_blocked_or_not_blocked(
        self, block_type: BlockType
    ):
        """
        If all versions are either blocked or not blocked, skip the update.
        """
        for _ in range(0, 10):
            self._block_version(block_type=block_type)

        upload_mlbf_to_remote_settings()
        assert self.mocks['olympia.blocklist.cron.upload_filter.delay'].called

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
                filter_list=[],
                create_stash=True,
            )
            in self.mocks['olympia.blocklist.cron.upload_filter.delay'].call_args_list
        )

    def test_pass_correct_arguments_to_upload_filter(self):
        self.mocks['olympia.blocklist.cron.upload_filter.delay'].stop()
        with mock.patch(
            'olympia.blocklist.cron.upload_filter.delay', wraps=upload_filter.delay
        ) as spy_delay:
            upload_mlbf_to_remote_settings(force_base=True)
            spy_delay.assert_called_with(
                self.current_time,
                filter_list=[BlockType.BLOCKED.name],
                create_stash=False,
            )
            with override_switch('enable-soft-blocking', active=True):
                upload_mlbf_to_remote_settings(force_base=True)
                spy_delay.assert_called_with(
                    self.current_time,
                    filter_list=[BlockType.BLOCKED.name, BlockType.SOFT_BLOCKED.name],
                    create_stash=False,
                )


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
        for block_type in BlockType:
            assert get_base_generation_time(block_type) is None
            set_config(MLBF_BASE_ID_CONFIG_KEY(block_type, compat=True), 123)
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
