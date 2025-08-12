import json
import uuid

from django.conf import settings
from django.core import mail

import pytest
import responses

from olympia import amo
from olympia.amo.tests import addon_factory, user_factory, version_factory
from olympia.blocklist.models import Block, BlockType, BlockVersion
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import PromotedGroup

from ..models import ContentDecision
from ..utils import reject_and_block_addons


@pytest.mark.django_db
def test_reject_and_block_addons():
    user_factory(id=settings.TASK_USER_ID)
    normal_addon = addon_factory(users=[user_factory()])
    normal_addon_version = normal_addon.current_version
    PromotedGroup.objects.get_or_create(
        group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED, high_profile=True
    )
    recommended_addon = addon_factory(
        promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
        users=[user_factory()],
        version_kw={'promotion_approved': False},
    )
    partially_blocked_addon = addon_factory(users=[user_factory()])
    partially_blocked_version = partially_blocked_addon.current_version
    hard_blocked_version = version_factory(
        addon=partially_blocked_addon, file_kw={'status': amo.STATUS_DISABLED}
    )
    BlockVersion.objects.create(
        block=Block.objects.create(
            guid=partially_blocked_addon.guid,
            updated_by=user_factory(),
            reason='something',
        ),
        version=hard_blocked_version,
        block_type=BlockType.BLOCKED,
    )
    addons = [
        normal_addon,
        recommended_addon,
        partially_blocked_addon,
    ]
    responses.add_callback(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
    )

    reject_and_block_addons(addons)

    assert normal_addon.block
    assert not recommended_addon.block
    assert partially_blocked_addon.block

    assert normal_addon_version.blockversion.block_type == BlockType.SOFT_BLOCKED
    assert partially_blocked_version.blockversion.block_type == BlockType.SOFT_BLOCKED
    # we didn't accidently downgrade the hard-blocked version
    assert hard_blocked_version.blockversion.block_type == BlockType.BLOCKED

    # 3 decisions; 2 are immediately executed; one is recommended so held for 2nd level
    assert ContentDecision.objects.count() == 3
    assert ContentDecision.objects.filter(action_date__isnull=False).count() == 2
    assert not ContentDecision.objects.filter(addon=recommended_addon).get().action_date

    assert len(mail.outbox) == 2  # One for normal, one for partially blocked
    assert mail.outbox[0].to == [normal_addon.authors.get().email]
    assert mail.outbox[1].to == [partially_blocked_addon.authors.get().email]
    # no email yet for recommended addon - it would come after the 2nd level review
