from datetime import datetime

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia import amo
from olympia.abuse.models import CinderPolicy
from olympia.activity.models import ActivityLog, CinderPolicyLog, ReviewActionReasonLog
from olympia.reviewers.models import ReviewActionReason


log = olympia.core.logger.getLogger(
    'z.reviewers.backfill_reviewactionreasons_for_delayed_rejections'
)


class Command(BaseCommand):
    help = 'Backfill ReviewActionReasons in eventual delayed Reject'
    expired_from_delayed_action_ids = {
        amo.LOG.AUTO_REJECT_CONTENT_AFTER_DELAY_EXPIRED.id: (
            amo.LOG.REJECT_CONTENT_DELAYED.id
        ),
        amo.LOG.AUTO_REJECT_VERSION_AFTER_DELAY_EXPIRED.id: (
            amo.LOG.REJECT_VERSION_DELAYED.id
        ),
    }
    # To reduce the risk of fixing something badly, and making it worse, we're
    # limiting the fix to a period from the start of 2025 to early March.
    MIN_DATE = datetime(2025, 1, 1)
    MAX_DATE = datetime(2025, 3, 6)

    def handle(self, *args, **options):
        rejections = ActivityLog.objects.filter(
            # one of the expired rejection reasons
            action__in=self.expired_from_delayed_action_ids.keys(),
            # with no review action reasons currently
            reviewactionreasonlog__id=None,
            created__gte=self.MIN_DATE,
            created__lte=self.MAX_DATE,
        ).exclude(versionlog__id=None)
        log.info('%s Rejections to fix', rejections.count())
        for alog in rejections:
            versions_qs = alog.versionlog_set.values_list('version', flat=True)
            reasons = self.fix_rejection_reasons(alog, versions_qs)
            policies = self.fix_rejection_policies(alog, versions_qs)
            alog.set_arguments(
                alog.arguments
                + [(ReviewActionReason, r_id) for r_id in reasons]
                + [(CinderPolicy, p_id) for p_id in policies]
            )
            alog.save()
        log.info('%s Rejections fixed', rejections.count())

    def fix_rejection_reasons(self, alog, versions_qs):
        # collect the reasons that the delayed rejection had
        reasons_from_activities_qs = (
            ReviewActionReasonLog.objects.filter(
                activity_log__action=self.expired_from_delayed_action_ids[alog.action],
                activity_log__versionlog__version__in=versions_qs,
                created__lte=alog.created,
                created__gte=self.MIN_DATE,
            )
            .order_by('created')
            .values_list('activity_log__versionlog__version_id', 'reason_id')
        )
        # de-dupe into a set and filter out older versionlogs for the same version
        rejection_reasons = {
            reason_id
            for reason_id in {
                v_id: r_id for v_id, r_id in reasons_from_activities_qs
            }.values()
        }

        # create ReviewActionReasonLog instances for each reason to fk them
        ReviewActionReasonLog.objects.bulk_create(
            ReviewActionReasonLog(activity_log=alog, reason_id=reason_id)
            for reason_id in rejection_reasons
        )
        return rejection_reasons

    def fix_rejection_policies(self, alog, versions_qs):
        # collect the policies that the delayed rejection had
        policies_from_activities_qs = (
            CinderPolicyLog.objects.filter(
                activity_log__action=self.expired_from_delayed_action_ids[alog.action],
                activity_log__versionlog__version__in=versions_qs,
                created__lte=alog.created,
                created__gte=self.MIN_DATE,
            )
            .order_by('created')
            .values_list('activity_log__versionlog__version_id', 'cinder_policy_id')
        )
        # de-dupe into a set and filter out older versionlogs for the same version
        rejection_policies = {
            policy_id
            for policy_id in {
                v_id: p_id for v_id, p_id in policies_from_activities_qs
            }.values()
        }

        # create CinderPolicy instances for each policy to fk them
        CinderPolicyLog.objects.bulk_create(
            CinderPolicyLog(activity_log=alog, cinder_policy_id=policy_id)
            for policy_id in rejection_policies
        )
        for decision_log in alog.contentdecisionlog_set.all():
            # update the decision(s) to link to the cinder policies too
            decision_log.decision.policies.add(
                *(cinder_policy_id for cinder_policy_id in rejection_policies)
            )
        return rejection_policies
