import json
import uuid
from datetime import datetime

from django.conf import settings

import responses

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, user_factory

from ..models import Block, BlocklistSubmission
from ..utils import datetime_to_ts, save_versions_to_blocks


def test_datetime_to_ts():
    now = datetime.now()
    assert datetime_to_ts(now) == int(now.timestamp() * 1000)


class TestSaveVersionsToBlocks(TestCase):
    def setUp(self):
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        responses.add_callback(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
        )

    def test_metadata_updates(self):
        user_new = user_factory()
        addon = addon_factory()
        existing_block = Block.objects.create(
            guid=addon.guid,
            updated_by=self.task_user,
            reason='old reason',
            url='old url',
        )
        submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, reason='new reason', url=None, updated_by=user_new
        )
        save_versions_to_blocks([addon.guid], submission)

        existing_block.reload()
        assert existing_block.reason == 'new reason'
        assert existing_block.url == 'old url'
        assert existing_block.updated_by == user_new

    def test_log_entries_new_block(self):
        user_new = user_factory()
        addon = addon_factory()
        submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid,
            reason='some reason',
            url=None,
            updated_by=user_new,
            disable_addon=True,
            changed_version_ids=[addon.current_version.pk],
        )
        ActivityLog.objects.all().delete()

        save_versions_to_blocks([addon.guid], submission)

        assert ActivityLog.objects.count() == 4
        assert list(
            ActivityLog.objects.order_by('pk').values_list('action', flat=True)
        ) == [
            amo.LOG.BLOCKLIST_BLOCK_ADDED.id,
            amo.LOG.BLOCKLIST_VERSION_BLOCKED.id,
            amo.LOG.CHANGE_STATUS.id,
            amo.LOG.REJECT_VERSION.id,
        ]

        activity = ActivityLog.objects.latest('pk')
        assert activity.action == amo.LOG.REJECT_VERSION.id
        assert activity.user == self.task_user
        assert activity.details['comments'] == 'some reason'
        assert activity.details['is_addon_being_blocked']
        assert activity.details['is_addon_being_disabled']

    def test_no_empty_new_blocks(self):
        user_new = user_factory()
        addon = addon_factory()
        submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid,
            reason='reason',
            url='url',
            updated_by=user_new,
            changed_version_ids=[],
        )
        save_versions_to_blocks([addon.guid], submission)

        assert not Block.objects.exists()
