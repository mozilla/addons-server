import functools
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import translation

import requests
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import to_language
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.users.models import UserProfile

from .cinder import CinderAddonHandledByLegal
from .models import (
    AbuseReport,
    AbuseReportManager,
    CinderJob,
    CinderPolicy,
    ContentDecision,
)


log = olympia.core.logger.getLogger('z.abuse')


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
        .filter(
            ~AbuseReportManager.is_individually_actionable_q(),
            guid=OuterRef('guid'),
            created__gte=datetime.now() - timedelta(days=14),
        )
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
        qs, NeedsHumanReview.REASONS.ABUSE_REPORTS_THRESHOLD
    )


def retryable_task(f):
    retryable_exceptions = (requests.RequestException,)

    @task(
        autoretry_for=retryable_exceptions,
        retry_backoff=30,  # start backoff at 30 seconds
        retry_backoff_max=2 * 60 * 60,  # Max out at 2 hours between retries
        # With jitter we don't know the total time period for retries, but we're aiming
        # for ~72 hours
        retry_kwargs={'max_retries': 60},
        bind=True,
    )
    @functools.wraps(f)
    def wrapper(task, *args, **kw):
        function_name = f.__name__
        try:
            f(*args, **kw)
        except Exception as exc:
            retry_count = task.request.retries
            statsd.incr(f'abuse.tasks.{function_name}.failure')
            if isinstance(exc, retryable_exceptions) and retry_count == 0:
                log.exception(f'Retrying Celery Task {function_name}', exc_info=exc)
            raise
        else:
            statsd.incr(f'abuse.tasks.{function_name}.success')

    return wrapper


@retryable_task
@use_primary_db
def report_to_cinder(abuse_report_id):
    abuse_report = AbuseReport.objects.get(pk=abuse_report_id)
    with translation.override(
        to_language(abuse_report.application_locale or settings.LANGUAGE_CODE)
    ):
        CinderJob.report(abuse_report)


@retryable_task
@use_primary_db
def appeal_to_cinder(
    *, decision_cinder_id, abuse_report_id, appeal_text, user_id, is_reporter
):
    decision = ContentDecision.objects.get(cinder_id=decision_cinder_id)
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


@retryable_task
@use_primary_db
def report_decision_to_cinder_and_notify(*, decision_id):
    decision = ContentDecision.objects.get(id=decision_id)
    entity_helper = CinderJob.get_entity_helper(
        decision.target,
        resolved_in_reviewer_tools=True,
    )
    decision.report_to_cinder(entity_helper)
    # We've already executed the action in the reviewer tools
    decision.send_notifications()


@retryable_task
@use_primary_db
def sync_cinder_policies():
    max_length = CinderPolicy._meta.get_field('name').max_length
    policies_in_use_q = (
        Q(contentdecision__id__gte=0)
        | Q(reviewactionreason__id__gte=0)
        | Q(expose_in_reviewer_tools=True)
    )

    def sync_policies(data, parent_id=None):
        policies_in_cinder = set()
        for policy in data:
            if (labels := [label['name'] for label in policy.get('labels', [])]) and (
                'AMO' not in labels
            ):
                # If the policy is labelled, but not for AMO, skip it
                continue
            policies_in_cinder.add(policy['uuid'])
            cinder_policy, _ = CinderPolicy.objects.update_or_create(
                uuid=policy['uuid'],
                defaults={
                    'name': policy['name'][:max_length],
                    'text': policy['description'],
                    'parent_id': parent_id,
                    'modified': datetime.now(),
                    'present_in_cinder': True,
                },
            )

            if nested := policy.get('nested_policies'):
                policies_in_cinder.update(sync_policies(nested, cinder_policy.id))
        return policies_in_cinder

    def delete_unused_orphaned_policies(policies_in_cinder):
        qs = CinderPolicy.objects.exclude(uuid__in=policies_in_cinder).exclude(
            policies_in_use_q
        )
        if qs.exists():
            log.info(
                'Deleting orphaned Cinder Policy not in use: %s',
                list(qs.values_list('uuid', flat=True)),
            )
            qs.delete()

    def mark_used_orphaned_policies(policies_in_cinder):
        qs = (
            CinderPolicy.objects.exclude(uuid__in=policies_in_cinder)
            .exclude(present_in_cinder=False)  # No need to mark those again.
            .filter(policies_in_use_q)
        )
        if qs.exists():
            log.info(
                'Marking orphaned Cinder Policy still in use as such: %s',
                list(qs.values_list('uuid', flat=True)),
            )
            qs.update(present_in_cinder=False)

    url = f'{settings.CINDER_SERVER_URL}policies'
    headers = {
        'accept': 'application/json',
        'content-type': 'application/json',
        'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    policies_in_cinder = sync_policies(data)
    delete_unused_orphaned_policies(policies_in_cinder)
    mark_used_orphaned_policies(policies_in_cinder)


@task
@use_primary_db
def handle_escalate_action(*, job_pk):
    old_job = CinderJob.objects.get(id=job_pk)
    entity_helper = CinderJob.get_entity_helper(
        old_job.target, resolved_in_reviewer_tools=True
    )
    job_id = entity_helper.workflow_recreate(notes=old_job.decision.notes, job=old_job)

    old_job.handle_job_recreated(new_job_id=job_id, resolvable_in_reviewer_tools=True)


@task
@use_primary_db
def handle_forward_to_legal_action(*, decision_pk):
    decision = ContentDecision.objects.get(id=decision_pk)
    old_job = getattr(decision, 'cinder_job', None)
    entity_helper = CinderAddonHandledByLegal(decision.addon)
    job_id = entity_helper.workflow_recreate(notes=decision.notes, job=old_job)

    if old_job:
        old_job.handle_job_recreated(
            new_job_id=job_id, resolvable_in_reviewer_tools=False
        )
    else:
        CinderJob.objects.update_or_create(
            job_id=job_id,
            defaults={
                'resolvable_in_reviewer_tools': False,
                'target_addon': decision.addon,
            },
        )
