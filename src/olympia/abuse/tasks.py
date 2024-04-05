from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import translation

import requests
from django_statsd.clients import statsd

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import to_language
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.users.models import UserProfile

from .models import AbuseReport, CinderDecision, CinderJob, CinderPolicy


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
    try:
        abuse_report = AbuseReport.objects.get(pk=abuse_report_id)
        with translation.override(
            to_language(abuse_report.application_locale or settings.LANGUAGE_CODE)
        ):
            CinderJob.report(abuse_report)
    except Exception:
        statsd.incr('abuse.tasks.report_to_cinder.failure')
        raise
    else:
        statsd.incr('abuse.tasks.report_to_cinder.success')


@task
@use_primary_db
def appeal_to_cinder(
    *, decision_cinder_id, abuse_report_id, appeal_text, user_id, is_reporter
):
    try:
        decision = CinderDecision.objects.get(cinder_id=decision_cinder_id)
        if abuse_report_id:
            abuse_report = AbuseReport.objects.get(id=abuse_report_id)
        else:
            abuse_report = None
        if user_id:
            user = UserProfile.objects.get(pk=user_id)
        else:
            # If no user is passed then they were anonymous, caller should have
            # verified appeal was allowed, so the appeal is coming from the
            # anonymous reporter and we have their name/email in the abuse report
            # already.
            user = None
        decision.appeal(
            abuse_report=abuse_report,
            appeal_text=appeal_text,
            user=user,
            is_reporter=is_reporter,
        )
    except Exception:
        statsd.incr('abuse.tasks.appeal_to_cinder.failure')
        raise
    else:
        statsd.incr('abuse.tasks.appeal_to_cinder.success')


@task
@use_primary_db
def resolve_job_in_cinder(*, cinder_job_id, log_entry_id):
    try:
        cinder_job = CinderJob.objects.get(id=cinder_job_id)
        log_entry = ActivityLog.objects.get(id=log_entry_id)
        cinder_job.resolve_job(log_entry=log_entry)
    except Exception:
        statsd.incr('abuse.tasks.resolve_job_in_cinder.failure')
        raise
    else:
        statsd.incr('abuse.tasks.resolve_job_in_cinder.success')


@task
@use_primary_db
def notify_addon_decision_to_cinder(*, log_entry_id, addon_id=None):
    try:
        log_entry = ActivityLog.objects.get(id=log_entry_id)
        addon = Addon.unfiltered.get(id=addon_id)
        decision = CinderDecision(addon=addon)
        decision.notify_reviewer_decision(
            log_entry=log_entry,
            entity_helper=CinderJob.get_entity_helper(
                decision.target, resolved_in_reviewer_tools=True
            ),
        )
    except Exception:
        statsd.incr('abuse.tasks.notify_addon_decision_to_cinder.failure')
        raise
    else:
        statsd.incr('abuse.tasks.notify_addon_decision_to_cinder.success')


@task
@use_primary_db
def sync_cinder_policies():
    max_length = CinderPolicy._meta.get_field('name').max_length

    def sync_policies(policies, parent_id=None):
        for policy in policies:
            cinder_policy, _ = CinderPolicy.objects.update_or_create(
                uuid=policy['uuid'],
                defaults={
                    'name': policy['name'][:max_length],
                    'text': policy['description'],
                    'parent_id': parent_id,
                },
            )

            if nested := policy.get('nested_policies'):
                sync_policies(nested, cinder_policy.id)

    try:
        url = f'{settings.CINDER_SERVER_URL}policies'
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        sync_policies(data)
    except Exception:
        statsd.incr('abuse.tasks.sync_cinder_policies.failure')
        raise
    else:
        statsd.incr('abuse.tasks.sync_cinder_policies.success')
