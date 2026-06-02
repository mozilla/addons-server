import itertools
from collections import namedtuple
from datetime import datetime

from django.conf import settings

from olympia.constants.abuse import DECISION_ACTIONS


def reject_and_block_addons(addons, *, reject_reason):
    from .models import CinderPolicy, ContentDecision
    from .tasks import report_decision_to_cinder_and_notify

    for addon in addons:
        decision = ContentDecision.objects.create(
            addon=addon,
            action=DECISION_ACTIONS.AMO_BLOCK_ADDON,
            reviewer_user_id=settings.TASK_USER_ID,
            metadata={ContentDecision.POLICY_DYNAMIC_VALUES: {}},
        )
        decision.policies.set(
            CinderPolicy.objects.filter(
                enforcement_actions__contains=decision.action.api_value
            )
        )
        log_entry = decision.execute_action()
        if log_entry:
            # we're adding this afterwards so there isn't an unnecessary activity log
            notes = f'Rejected and blocked due to: {reject_reason}'
            decision.update(private_notes=notes)
            log_entry.details = {**log_entry.details, 'reason': notes}
            log_entry.save()

        report_decision_to_cinder_and_notify.delay(decision_id=decision.id)


def get_instance_from_entity(entity_schema, entity_id):
    from olympia.addons.models import Addon
    from olympia.bandwagon.models import Collection
    from olympia.ratings.models import Rating
    from olympia.users.models import UserProfile

    try:
        instance_id = int(entity_id)
    except (ValueError, TypeError):
        return None

    match entity_schema:
        case 'amo_addon':
            model_manager = Addon.unfiltered
        case 'amo_collection':
            model_manager = Collection.unfiltered
        case 'amo_rating':
            model_manager = Rating.unfiltered
        case 'amo_user':
            model_manager = UserProfile.objects
        case _:
            return None

    return model_manager.filter(id=instance_id).first()


def is_same_time(instance, created_string):
    """
    Check if an entity is from this environment by checking the created date.
    We need to do this as we share the same staging Cinder instance for
    addons-dev, addons stage, and local development.
    """
    instance_time = instance.created.replace(microsecond=0)
    string_time = datetime.fromisoformat(created_string).replace(microsecond=0)
    return instance_time == string_time


SplitEnforcementActions = namedtuple('SplitEnforcementActions', ['primary', 'followup'])


def split_enforcement_actions(enforcement_action_slugs):
    """Convert enforcement action slugs into enums and split them into primary and
    follow-up actions."""
    actions = [
        action
        for action_slug in enforcement_action_slugs
        if action_slug in DECISION_ACTIONS.api_values
        and (action := DECISION_ACTIONS.from_api_value(action_slug))
    ]
    primary_enforcement_actions = []
    followup_actions = []
    for action in actions:
        if action.value in DECISION_ACTIONS.FOLLOWUP_CINDER_ACTIONS.values:
            followup_actions.append(action)
        else:
            primary_enforcement_actions.append(action)
    return SplitEnforcementActions(
        tuple(primary_enforcement_actions), tuple(followup_actions)
    )


def filter_enforcement_actions(enforcement_actions, target_class):
    """Filter enforcement action enums according to what is applicable to the
    specified target.

    Return a tuple of actions. If enforcement_actions is SplitEnforcementActions, it
    will return a SplitEnforcementActions"""
    from .actions import CONTENT_ACTION_FROM_DECISION_ACTION

    if enforcement_actions and isinstance(enforcement_actions, SplitEnforcementActions):
        return SplitEnforcementActions(
            filter_enforcement_actions(enforcement_actions.primary, target_class),
            filter_enforcement_actions(enforcement_actions.followup, target_class),
        )

    return tuple(
        action
        for action in enforcement_actions
        if target_class
        in CONTENT_ACTION_FROM_DECISION_ACTION[action.value].valid_targets
    )


def hash_addon_negative_actions(actions):
    """Order negative actions according to their severity, as defined in
    DECISION_ACTIONS.ADDON_NEGATIVE_SORTED and return a bytestring to sort with.
    """
    return bytes(
        sorted(
            (
                DECISION_ACTIONS.ADDON_NEGATIVE_SORTED.values.index(action)
                for action in itertools.chain.from_iterable(actions)
                if action in DECISION_ACTIONS.ADDON_NEGATIVE_SORTED.values
            ),
            reverse=True,
        )
    )


def find_automated_enforcement_actions_from_policies(*, policies, addon, version):
    """Function to return what enforcement actions automation should use based
    on policies that were hit for a given add-on and version.

    We remove policies for a decision that a successful appeal against, filter
    out any non-applicable actions, and return the most aggressive
    action + follow-up actions we are left with.

    Return a SplitEnforcementActions namedtuple with primary and follow-up actions."""
    from .actions import CONTENT_ACTION_FROM_DECISION_ACTION
    from .models import ContentDecision

    # Default is to return no action + no follow-up actions
    most_aggressive_actions = SplitEnforcementActions((), ())
    for policy in policies:
        # Successful appeal for that same decision against the add-on (ignoring
        # versions) means we should skip automation.
        successful_appeal = ContentDecision.objects.filter(
            addon=addon,
            action__in=DECISION_ACTIONS.NON_OFFENDING.values,
            cinder_job__appealed_decisions__policies=policy,
        ).exists()
        if successful_appeal:
            continue

        enforcement_actions = filter_enforcement_actions(
            policy.split_enforcement_actions, addon.__class__
        )
        if len(enforcement_actions.primary) != 1:
            # That shouldn't happen: scanner rules should only have policies
            # that have relevant actions for add-ons (and only 1 primary action
            # for add-ons should be set)
            continue
        action = enforcement_actions.primary[0]
        ContentActionClass = CONTENT_ACTION_FROM_DECISION_ACTION[action]
        if (
            action not in DECISION_ACTIONS.ADDON_NEGATIVE_SORTED
            or ContentActionClass.should_be_skipped_by_automation(
                addon=addon, version=version
            )
        ):
            continue

        if hash_addon_negative_actions(
            enforcement_actions
        ) > hash_addon_negative_actions(most_aggressive_actions):
            most_aggressive_actions = enforcement_actions
    return most_aggressive_actions
