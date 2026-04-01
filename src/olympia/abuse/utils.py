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
