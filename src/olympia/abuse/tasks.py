from datetime import datetime, timedelta

from django.db.models import Count, F, OuterRef, Q, Subquery

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.reviewers.models import NeedsHumanReview, UsageTier

from .models import AbuseReport, CinderReport


@task
def flag_high_abuse_reports_addons_according_to_review_tier():
    usage_tiers = UsageTier.objects.filter(
        # Tiers with no upper adu threshold are special cases with their own
        # way of flagging add-ons for review (either notable or promoted).
        upper_adu_threshold__isnull=False,
        # Need a abuse reports ratio threshold to be set for the tier.
        abuse_reports_ratio_threshold_before_flagging__isnull=False,
    )

    tier_filters = Q()
    for usage_tier in usage_tiers:
        tier_filters |= Q(
            average_daily_users__gte=usage_tier.lower_adu_threshold,
            average_daily_users__lt=usage_tier.upper_adu_threshold,
            abuse_reports_count__gte=F('average_daily_users')
            * usage_tier.abuse_reports_ratio_threshold_before_flagging
            / 100,
        )
    if not tier_filters:
        return

    abuse_reports_count_qs = (
        AbuseReport.objects.values('guid')
        .filter(guid=OuterRef('guid'), created__gte=datetime.now() - timedelta(days=14))
        .annotate(guid_abuse_reports_count=Count('*'))
        .values('guid_abuse_reports_count')
        .order_by()
    )
    qs = (
        Addon.unfiltered.exclude(status=amo.STATUS_DISABLED)
        .filter(type=amo.ADDON_EXTENSION)
        .annotate(abuse_reports_count=Subquery(abuse_reports_count_qs))
        .filter(tier_filters)
    )
    NeedsHumanReview.set_on_addons_latest_signed_versions(
        qs, NeedsHumanReview.REASON_ABUSE_REPORTS_THRESHOLD
    )


@task
def report_to_cinder(abuse_report_id):
    abuse_report = AbuseReport.objects.filter(id=abuse_report_id).first()
    if not abuse_report:
        return
    cinder_report = CinderReport.objects.create(abuse_report=abuse_report)
    cinder_report.report()
