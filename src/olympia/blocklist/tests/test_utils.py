from datetime import datetime

from django.conf import settings

import pytest

from olympia.amo.tests import addon_factory, user_factory

from ..models import Block, BlocklistSubmission
from ..utils import datetime_to_ts, save_versions_to_blocks


def test_datetime_to_ts():
    now = datetime.now()
    assert datetime_to_ts(now) == int(now.timestamp() * 1000)


@pytest.mark.django_db
def test_save_versions_to_blocks_metadata_updates():
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
