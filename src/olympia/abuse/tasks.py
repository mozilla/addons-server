from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import translation

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import to_language
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.users.models import UserProfile

from .models import AbuseReport, CinderJob, CinderPolicy


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
@use_primary_db
def report_to_cinder(abuse_report_id):
    abuse_report = AbuseReport.objects.filter(id=abuse_report_id).first()
    if not abuse_report:
        return
    with translation.override(
        to_language(abuse_report.application_locale or settings.LANGUAGE_CODE)
    ):
        CinderJob.report(abuse_report)


@task
@use_primary_db
def appeal_to_cinder(*, abuse_report_id, appeal_text, user_id):
    abuse_report = AbuseReport.objects.get(id=abuse_report_id)
    if user_id:
        user = UserProfile.objects.get(pk=user_id)
    else:
        # If no user is passed then they were anonymous, caller should have
        # verified appeal was allowed, so the appeal is coming from the
        # anonymous reporter and we have their name/email in the abuse report
        # already.
        user = None
    abuse_report.cinder_job.appeal(abuse_report, appeal_text, user)


@task
@use_primary_db
def resolve_job_in_cinder(*, cinder_job_id, review_text, decision, policy_ids):
    cinder_job = CinderJob.objects.get(id=cinder_job_id)
    policies = CinderPolicy.objects.filter(id__in=policy_ids)
    cinder_job.resolve_job(review_text, decision, policies)
