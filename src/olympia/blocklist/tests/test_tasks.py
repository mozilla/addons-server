import json
import os
from datetime import datetime, timedelta
from typing import Dict, List
from unittest import TestCase, mock

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core.exceptions import SuspiciousOperation
from django.test.testcases import TransactionTestCase

import pytest

from olympia.amo.tests import (
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.mlbf import MLBF
from olympia.constants.blocklist import MLBF_BASE_ID_CONFIG_KEY, MLBF_TIME_CONFIG_KEY
from olympia.zadmin.models import set_config

from ..models import BlocklistSubmission, BlockType, BlockVersion
from ..tasks import (
    BLOCKLIST_RECORD_MLBF_BASE,
    cleanup_old_files,
    process_blocklistsubmission,
    upload_filter,
)
from ..utils import datetime_to_ts


def test_cleanup_old_files():
    mlbf_path = settings.MLBF_STORAGE_PATH
    six_month_date = datetime.now() - timedelta(weeks=26)

    now_dir = os.path.join(mlbf_path, str(datetime_to_ts()))
    os.mkdir(now_dir)

    over_six_month_dir = os.path.join(
        mlbf_path, str(datetime_to_ts(six_month_date - timedelta(days=1)))
    )
    os.mkdir(over_six_month_dir)
    with open(os.path.join(over_six_month_dir, 'f'), 'w') as over:
        over.write('.')  # create a file that'll be deleted too

    under_six_month_dir = os.path.join(
        mlbf_path, str(datetime_to_ts(six_month_date - timedelta(days=-1)))
    )
    os.mkdir(under_six_month_dir)

    cleanup_old_files(base_filter_id=9600100364318)  # sometime in the future
    assert os.path.exists(now_dir)
    assert os.path.exists(under_six_month_dir)
    assert not os.path.exists(over_six_month_dir)

    # repeat, but with a base filter id that's over 6 months
    os.mkdir(over_six_month_dir)  # recreate it

    after_base_date_dir = os.path.join(
        mlbf_path, str(datetime_to_ts(six_month_date - timedelta(weeks=1, days=1)))
    )
    os.mkdir(after_base_date_dir)
    with open(os.path.join(after_base_date_dir, 'f'), 'w') as over:
        over.write('.')  # create a file that'll be deleted too

    cleanup_old_files(
        base_filter_id=datetime_to_ts(six_month_date - timedelta(weeks=1))
    )
    assert os.path.exists(now_dir)
    assert os.path.exists(under_six_month_dir)
    assert os.path.exists(over_six_month_dir)
    assert not os.path.exists(after_base_date_dir)


class TestProcessBlocklistSubmission(TransactionTestCase):
    def setUp(self):
        user_factory(id=settings.TASK_USER_ID)
        self.addon = addon_factory(guid='guid@')
        self.submission = BlocklistSubmission.objects.create(
            input_guids=self.addon.guid,
            signoff_state=BlocklistSubmission.SIGNOFF_STATES.APPROVED,
        )

    def test_state_reset(self):
        with mock.patch.object(
            BlocklistSubmission,
            'save_to_block_objects',
            side_effect=SuspiciousOperation('Something happened!'),
        ):
            with self.assertRaises(SuspiciousOperation):
                # we know it's going to raise, we just want to capture it safely
                process_blocklistsubmission.delay(self.submission.id)
        self.submission.reload()
        assert (
            self.submission.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PENDING
        )
        log_entry = LogEntry.objects.get()
        assert log_entry.user.id == settings.TASK_USER_ID
        assert log_entry.change_message == 'Exception in task: Something happened!'

    @mock.patch.object(BlocklistSubmission, 'save_to_block_objects')
    @mock.patch.object(BlocklistSubmission, 'delete_block_objects')
    def test_calls_save_to_block_objects_or_delete_block_objects_depending_on_action(
        self, delete_block_objects_mock, save_to_block_objects_mock
    ):
        for action in (
            BlocklistSubmission.ACTIONS.ADDCHANGE,
            BlocklistSubmission.ACTIONS.HARDEN,
            BlocklistSubmission.ACTIONS.SOFTEN,
        ):
            save_to_block_objects_mock.reset_mock()
            delete_block_objects_mock.reset_mock()
            self.submission.update(action=action)
            process_blocklistsubmission(self.submission.id)
            assert save_to_block_objects_mock.call_count == 1
            assert delete_block_objects_mock.call_count == 0
        for action in (BlocklistSubmission.ACTIONS.DELETE,):
            save_to_block_objects_mock.reset_mock()
            delete_block_objects_mock.reset_mock()
            self.submission.update(action=action)
            process_blocklistsubmission(self.submission.id)
            assert save_to_block_objects_mock.call_count == 0
            assert delete_block_objects_mock.call_count == 1


@pytest.mark.django_db
class TestUploadMLBFToRemoteSettings(TestCase):
    def _attachment(self, id, attachment_type, generation_time):
        return {
            'id': id,
            'attachment': {},
            'generation_time': generation_time,
            'attachment_type': attachment_type,
        }

    def _stash(self, id, stash_time):
        return {'id': id, 'stash': {}, 'stash_time': stash_time}

    def setUp(self):
        self.user = user_factory()
        self.addon = addon_factory()
        self.block = block_factory(guid=self.addon.guid, updated_by=self.user)

        prefix = 'olympia.blocklist.tasks.'
        self.mocks = {
            'records': f'{prefix}RemoteSettings.records',
            'delete_record': f'{prefix}RemoteSettings.delete_record',
            'publish_attachment': f'{prefix}RemoteSettings.publish_attachment',
            'publish_record': f'{prefix}RemoteSettings.publish_record',
            'complete_session': f'{prefix}RemoteSettings.complete_session',
            'set_config': f'{prefix}set_config',
            'statsd.incr': f'{prefix}statsd.incr',
            'cleanup_old_files.delay': f'{prefix}cleanup_old_files.delay',
        }
        for mock_name, mock_path in self.mocks.items():
            patcher = mock.patch(mock_path)
            self.addCleanup(patcher.stop)
            self.mocks[mock_name] = patcher.start()

        self.generation_time = datetime_to_ts(datetime.now())

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

    def test_server_setup(self):
        pass

    def test_statsd_increments(self):
        pass

    def test_invalid_block_type_raises(self):
        with self.assertRaises(ValueError):
            BLOCKLIST_RECORD_MLBF_BASE('foo')

        with self.assertRaises(KeyError):
            upload_filter.delay(
                self.generation_time,
                filter_list=['foo'],
            )

    def _test_upload_base_filter(self, *block_types: BlockType):
        self._block_version(is_signed=True)
        mlbf = MLBF.generate_from_db(self.generation_time)
        for block_type in block_types:
            mlbf.generate_and_write_filter(block_type)

        upload_filter.delay(
            self.generation_time,
            filter_list=[block_type.name for block_type in block_types],
        )

        assert not self.mocks['delete_record'].called
        actual_files = [
            mock[0][1][1].name
            for mock in self.mocks['publish_attachment'].call_args_list
        ]

        for block_type in block_types:
            with mlbf.storage.open(mlbf.filter_path(block_type), 'rb') as filter_file:
                assert filter_file.name in actual_files
                expected_call = mock.call(
                    {
                        'key_format': MLBF.KEY_FORMAT,
                        'generation_time': self.generation_time,
                        'attachment_type': BLOCKLIST_RECORD_MLBF_BASE(block_type),
                    },
                    ('filter.bin', mock.ANY, 'application/octet-stream'),
                )
                assert expected_call in self.mocks['publish_attachment'].call_args_list

        assert self.mocks['complete_session'].called
        assert (
            mock.call(MLBF_TIME_CONFIG_KEY, self.generation_time, json_value=True)
        ) in self.mocks['set_config'].call_args_list

        for block_type in block_types:
            if block_type == BlockType.BLOCKED:
                # We currently write to the old singular config key for hard blocks
                # to preserve backward compatibility.
                # In https://github.com/mozilla/addons/issues/15193
                # we can remove this and start writing to the new plural key.
                assert (
                    mock.call(
                        MLBF_BASE_ID_CONFIG_KEY(block_type, compat=True),
                        self.generation_time,
                        json_value=True,
                    )
                ) in self.mocks['set_config'].call_args_list
            assert (
                mock.call(
                    MLBF_BASE_ID_CONFIG_KEY(block_type),
                    self.generation_time,
                    json_value=True,
                )
            ) in self.mocks['set_config'].call_args_list

    def test_upload_blocked_filter(self):
        self._test_upload_base_filter(BlockType.BLOCKED)

    def test_upload_soft_blocked_filter(self):
        self._test_upload_base_filter(BlockType.SOFT_BLOCKED)

    def test_upload_soft_and_blocked_filter(self):
        self._test_upload_base_filter(BlockType.BLOCKED, BlockType.SOFT_BLOCKED)

    def _test_cleanup_old_records(
        self,
        filter_list: Dict[BlockType, int],
        records: List[Dict[str, int]],
        expected_calls: List[any],
    ):
        self._block_version(is_signed=True)
        mlbf = MLBF.generate_from_db(self.generation_time)
        for block_type, base_id in filter_list.items():
            mlbf.generate_and_write_filter(block_type)
            # We currently write to the old singular config key for hard blocks
            # to preserve backward compatibility.
            # In https://github.com/mozilla/addons/issues/15193
            # we can remove this and start writing to the new plural key.
            set_config(
                MLBF_BASE_ID_CONFIG_KEY(block_type, compat=True),
                base_id,
                json_value=True,
            )

        self.mocks['records'].return_value = records
        upload_filter.delay(
            self.generation_time,
            filter_list=[block_type.name for block_type in filter_list],
        )

        assert self.mocks['delete_record'].call_args_list == expected_calls

        if len(filter_list.values()) > 0:
            self.mocks['cleanup_old_files.delay'].assert_called_with(
                base_filter_id=min(filter_list.values())
            )
            self.mocks['statsd.incr'].assert_called_with(
                'blocklist.tasks.upload_filter.reset_collection'
            )

    def test_skip_cleanup_when_no_filters(self):
        self._test_cleanup_old_records(
            filter_list={},
            records=[{'id': '0', 'generation_time': self.generation_time}],
            expected_calls=[],
        )

    def test_cleanup_old_records(self):
        """
        Clean up 0 because it's the only record matching the uploaded filters
        attachment_type or is older than generation_time.
        """
        self._test_cleanup_old_records(
            filter_list={
                BlockType.BLOCKED: self.generation_time,
            },
            records=[
                self._attachment(0, 'bloomfilter-base', self.generation_time - 1),
                self._attachment(
                    1, 'softblocks-bloomfilter-base', self.generation_time
                ),
                self._stash(2, self.generation_time + 1),
            ],
            expected_calls=[mock.call(0)],
        )

    def test_cleanup_oldest_stash_records(self):
        """
        The oldest base id time is (self.generation_time - 3)
        Delete 0 as matching attachment
        Delete 1 as older than base id
        """
        self._test_cleanup_old_records(
            filter_list={
                BlockType.BLOCKED: self.generation_time - 3,
            },
            records=[
                # Deleted, matching attachment
                self._attachment(0, 'bloomfilter-base', self.generation_time - 5),
                self._stash(
                    1, self.generation_time - 4
                ),  # deleted older than oldest filter
                # Not deleted, not matching attachment
                self._attachment(
                    1, 'softblocks-bloomfilter-base', self.generation_time - 3
                ),
                # Both Not delted, not older than oldest filter
                self._stash(1, self.generation_time - 2),
                self._stash(2, self.generation_time - 1),
            ],
            expected_calls=[mock.call(0), mock.call(1)],
        )

    def test_create_stashed_filter(self):
        old_mlbf = MLBF.generate_from_db(self.generation_time - 1)
        blocked_version = self._block_version(is_signed=True)
        mlbf = MLBF.generate_from_db(self.generation_time)
        mlbf.generate_and_write_stash(old_mlbf)

        upload_filter.delay(self.generation_time, create_stash=True)

        assert not self.mocks['delete_record'].called
        with mlbf.storage.open(mlbf.stash_path, 'rb') as stash_file:
            actual_stash = self.mocks['publish_record'].call_args_list[0][0][0]
            stash_data = json.load(stash_file)

            assert actual_stash == {
                'key_format': MLBF.KEY_FORMAT,
                'stash_time': self.generation_time,
                'stash': stash_data,
            }

            assert actual_stash['stash']['blocked'] == list(
                MLBF.hash_filter_inputs(
                    [(blocked_version.block.guid, blocked_version.version.version)]
                )
            )

        assert (
            mock.call('blocklist.tasks.upload_filter.upload_stash')
            in self.mocks['statsd.incr'].call_args_list
        )

        assert self.mocks['complete_session'].called
        assert (
            mock.call(MLBF_TIME_CONFIG_KEY, self.generation_time, json_value=True)
            in self.mocks['set_config'].call_args_list
        )

    def test_raises_when_no_filter_exists(self):
        with self.assertRaises(FileNotFoundError):
            upload_filter.delay(
                self.generation_time, filter_list=[BlockType.BLOCKED.name]
            )

    def test_raises_when_no_stash_exists(self):
        with self.assertRaises(FileNotFoundError):
            upload_filter.delay(self.generation_time, create_stash=True)

    def test_default_is_no_op(self):
        MLBF.generate_from_db(self.generation_time).generate_and_write_filter(
            BlockType.BLOCKED
        )
        upload_filter.delay(self.generation_time)
        assert not self.mocks['delete_record'].called
        assert not self.mocks['publish_record'].called
