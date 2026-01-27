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
