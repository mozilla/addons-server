from datetime import datetime

from django.conf import settings

from olympia.amo.tests import TestCase, addon_factory, user_factory

from ..models import Block, BlocklistSubmission
from ..utils import datetime_to_ts, save_versions_to_blocks


def test_datetime_to_ts():
    now = datetime.now()
    assert datetime_to_ts(now) == int(now.timestamp() * 1000)


class TestSaveVersionsToBlocks(TestCase):
    def test_metadata_updates(self):
        user_old = user_factory(pk=settings.TASK_USER_ID)
        user_new = user_factory()
        addon = addon_factory()
        existing_block = Block.objects.create(
            guid=addon.guid,
            updated_by=user_old,
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
