import json
import uuid
from unittest import mock

from django.conf import settings
from django.core import mail

import pytest
import responses

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.bandwagon.models import Collection
from olympia.blocklist.models import Block, BlockVersion
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.blocklist import BlockReason, BlockType
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import PromotedGroup
from olympia.ratings.models import Rating

from ..actions import ContentActionBlockAddon
from ..models import CinderJob, CinderPolicy, ContentDecision
from ..utils import (
    find_automated_enforcement_actions_from_policies,
    get_instance_from_entity,
    is_same_time,
    reject_and_block_addons,
)


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
            reason='Something!',
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
        f'{settings.CINDER_SERVER_URL}v1/create_decision',
        callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
    )

    reject_and_block_addons(addons, reject_reason='violation!')

    assert normal_addon.block
    assert not recommended_addon.block
    assert partially_blocked_addon.block

    assert normal_addon_version.blockversion.block_type == BlockType.SOFT_BLOCKED
    assert partially_blocked_version.blockversion.block_type == BlockType.SOFT_BLOCKED
    # we didn't accidently downgrade the hard-blocked version
    assert hard_blocked_version.blockversion.block_type == BlockType.BLOCKED

    assert (
        normal_addon_version.blockversion.auto_block_reason
        == BlockReason.FRAUD_DECEPTIVE
    )
    assert (
        partially_blocked_version.blockversion.auto_block_reason
        == BlockReason.FRAUD_DECEPTIVE
    )
    assert hard_blocked_version.blockversion.auto_block_reason is None  # didn't set

    assert normal_addon.block.reason == ''
    assert partially_blocked_addon.block.reason == 'Something!'

    # 3 decisions; 2 are immediately executed; one is recommended so held for 2nd level
    assert ContentDecision.objects.count() == 3
    assert ContentDecision.objects.filter(action_date__isnull=False).count() == 2
    assert not ContentDecision.objects.filter(addon=recommended_addon).get().action_date

    assert len(mail.outbox) == 2  # One for normal, one for partially blocked
    assert mail.outbox[0].to == [normal_addon.authors.get().email]
    assert 'violation!' not in mail.outbox[0].body
    assert mail.outbox[1].to == [partially_blocked_addon.authors.get().email]
    assert 'violation!' not in mail.outbox[1].body
    # no email yet for recommended addon - it would come after the 2nd level review

    log_entries = ActivityLog.objects.filter(action=amo.LOG.FORCE_DISABLE.id)
    assert len(log_entries) == 2
    assert log_entries[0].details['reason'] == 'Rejected and blocked due to: violation!'
    assert log_entries[1].details['reason'] == 'Rejected and blocked due to: violation!'
    log_entries = ActivityLog.objects.filter(
        action=amo.LOG.HELD_ACTION_FORCE_DISABLE.id
    )
    assert len(log_entries) == 1
    assert log_entries[0].details['reason'] == 'Rejected and blocked due to: violation!'

    assert (
        ActivityLog.objects.filter(
            action=amo.LOG.BLOCKLIST_VERSION_SOFT_BLOCKED.id
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_get_instance_from_entity():
    assert get_instance_from_entity('amo_addon', 'not a number') is None

    addon = addon_factory()
    assert get_instance_from_entity('amo_addon', addon.id) == addon
    assert get_instance_from_entity('amo_addon', 999999) is None
    assert get_instance_from_entity('no_entty', addon.id) is None

    collection = Collection.objects.create(name='Test', author=user_factory())
    assert get_instance_from_entity('amo_collection', collection.id) == collection

    rating = Rating.objects.create(addon=addon, user=user_factory(), rating=5)
    assert get_instance_from_entity('amo_rating', rating.id) == rating
    assert get_instance_from_entity('amo_rating', 999999) is None

    user = user_factory()
    assert get_instance_from_entity('amo_user', user.id) == user
    assert get_instance_from_entity('amo_user', 999999) is None


@pytest.mark.django_db
def test_is_same_time():
    addon = addon_factory()
    assert is_same_time(addon, addon.created.isoformat())
    assert is_same_time(addon, str(addon.created))
    assert not is_same_time(addon, str(addon.created.replace(year=2000)))
    assert is_same_time(addon, str(addon.created.replace(microsecond=1234)))


class TestFindAutomatedEnforcementActionsFromPolicies(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.version = self.addon.current_version

    def test_find_nothing(self):
        mild_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Mild Things',
            enforcement_actions=[],
        )
        invalid_action_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Invalid Things',
            enforcement_actions=['not-a-valid-action'],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[mild_things_policy, invalid_action_policy],
            addon=self.addon,
            version=self.version,
        )
        assert actions == []
        assert followup_actions == []

    def test_basic(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        slightly_less_bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Slightly Less Bad Things',
            enforcement_actions=[DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[bad_things_policy, slightly_less_bad_things_policy],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_DISABLE_ADDON]
        assert followup_actions == []

    def test_block_wins(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        extremely_bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Extremely Bad Things',
            enforcement_actions=['amo-block-addon'],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[bad_things_policy, extremely_bad_things_policy],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_BLOCK_ADDON]
        assert followup_actions == []

    def test_ordering_with_follow_up_action_against_not(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value],
        )
        bad_things_policy_with_more_aggressive_followup = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things, But Worse',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-short-soft-block-addon',
            ],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[
                bad_things_policy,
                bad_things_policy_with_more_aggressive_followup,
            ],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_DISABLE_ADDON]
        assert followup_actions == [
            DECISION_ACTIONS.AMO_FU_DELAY_SHORT_SOFT_BLOCK_ADDON
        ]

    def test_ordering_with_two_follow_up_actions_compared(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-short-soft-block-addon',
            ],
        )
        bad_things_policy_with_more_aggressive_followup = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things, But Worse',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-short-hard-block-addon',
            ],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[
                bad_things_policy,
                bad_things_policy_with_more_aggressive_followup,
            ],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_DISABLE_ADDON]
        assert followup_actions == [
            DECISION_ACTIONS.AMO_FU_DELAY_SHORT_HARD_BLOCK_ADDON
        ]

    def test_ordering_with_two_follow_up_actions_compared_different_delay(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-short-soft-block-addon',
            ],
        )
        bad_things_policy_with_less_delayed_followup = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things, But Slightly Worse',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-mid-hard-block-addon',
            ],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[bad_things_policy, bad_things_policy_with_less_delayed_followup],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_DISABLE_ADDON]
        assert followup_actions == [
            DECISION_ACTIONS.AMO_FU_DELAY_SHORT_SOFT_BLOCK_ADDON
        ]

    def test_ordering_with_multiple_followup_actions(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-short-soft-block-addon',
                'amo-fu-delay-mid-hard-block-addon',
            ],
        )
        bad_things_policy_with_delayed_followup = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things, But Slightly Worse',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-fu-delay-mid-hard-block-addon',
            ],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[bad_things_policy, bad_things_policy_with_delayed_followup],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_DISABLE_ADDON]
        assert followup_actions == [
            DECISION_ACTIONS.AMO_FU_DELAY_SHORT_SOFT_BLOCK_ADDON,
            DECISION_ACTIONS.AMO_FU_DELAY_MID_HARD_BLOCK_ADDON,
        ]

    @mock.patch.object(
        ContentActionBlockAddon,
        'should_be_skipped_by_automation',
        lambda **kwargs: True,
    )
    def test_skip_action_that_should_be_skipped_by_automation(self):
        bad_things_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Very Bad Things',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
            ],
        )
        worse_things_policy_that_should_be_skipped = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Worse Things',
            enforcement_actions=[
                # ContentActionBlockAddon.should_be_skipped_by_automation()
                # is mocked to return True so that should be skipped.
                'amo-block-addon',
            ],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[bad_things_policy, worse_things_policy_that_should_be_skipped],
            addon=self.addon,
            version=self.version,
        )
        assert actions == [DECISION_ACTIONS.AMO_DISABLE_ADDON]
        assert followup_actions == []

    def test_skip_policy_with_multiple_primary_actions(self):
        broken_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Multiple Relevant Enforcement Actions Policy',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'amo-block-addon',
            ],
        )
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[broken_policy],
            addon=self.addon,
            version=self.version,
        )
        assert actions == []
        assert followup_actions == []

    def test_skip_policy_if_successful_appeal_for_it_in_the_past(self):
        appealed_policy = CinderPolicy.objects.create(
            uuid=uuid.uuid4().hex,
            name='Policy that has been successfully appealed in the past',
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
            ],
        )
        appeal_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_APPROVE,
            cinder_job=CinderJob.objects.create(target_addon=self.addon),
        )
        original_decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            appeal_job=appeal_decision.cinder_job,
        )
        original_decision.policies.add(appealed_policy)
        actions, followup_actions = find_automated_enforcement_actions_from_policies(
            policies=[appealed_policy],
            addon=self.addon,
            version=self.version,
        )
        assert actions == []
        assert followup_actions == []
