from datetime import datetime, timedelta

import pytest

from olympia.amo.tests import addon_factory

from ..cron import (
    reports_without_cinder_id_qs,
    unresolved_cinder_handled_jobs_qs,
    unresolved_reviewers_handled_jobs_qs,
)
from ..models import AbuseReport, CinderJob


@pytest.mark.django_db
def test_reports_without_cinder_id_qs():
    just_over_one_hour_ago = datetime.now() - timedelta(hours=1, seconds=1)
    # over, with an id
    AbuseReport.objects.create(
        guid='3434@',
        cinder_job=CinderJob.objects.create(),
        created=just_over_one_hour_ago,
        reason=AbuseReport.REASONS.SOMETHING_ELSE,
    )
    # over, but not a reportable reason
    AbuseReport.objects.create(
        guid='56565@',
        created=just_over_one_hour_ago,
        reason=AbuseReport.REASONS.UNWANTED,
    )
    # under the sla
    AbuseReport.objects.create(
        guid='4545@',
        reason=AbuseReport.REASONS.SOMETHING_ELSE,
    )
    report = AbuseReport.objects.create(
        guid='56565@',
        created=just_over_one_hour_ago,
        reason=AbuseReport.REASONS.SOMETHING_ELSE,
    )
    assert list(reports_without_cinder_id_qs()) == [report]


@pytest.mark.django_db
def test_unresolved_cinder_handled_jobs_qs():
    just_over_three_days_ago = datetime.now() - timedelta(days=3, seconds=1)
    # over, but not a cinder handled job
    reviewer_handled = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(job_id=1, created=just_over_three_days_ago),
        location=AbuseReport.LOCATION.ADDON,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert reviewer_handled.is_handled_by_reviewers
    # under the sla
    under_sla = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(job_id=2),
        location=AbuseReport.LOCATION.AMO,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert not under_sla.is_handled_by_reviewers
    # over the sla
    over_sla = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(job_id=3, created=just_over_three_days_ago),
        location=AbuseReport.LOCATION.AMO,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert not over_sla.is_handled_by_reviewers
    # over, but resolved already
    resolved = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(
            job_id=4,
            created=just_over_three_days_ago,
            decision_action=CinderJob.DECISION_ACTIONS.AMO_DISABLE_ADDON,
        ),
        location=AbuseReport.LOCATION.AMO,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert not resolved.is_handled_by_reviewers
    assert list(unresolved_cinder_handled_jobs_qs()) == [over_sla.cinder_job]


@pytest.mark.django_db
def test_unresolved_reviewers_handled_jobs_qs():
    just_over_three_days_ago = datetime.now() - timedelta(days=3, seconds=1)
    # over, but not a reviewer handled job
    cinder_handled = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(job_id=1, created=just_over_three_days_ago),
        location=AbuseReport.LOCATION.AMO,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert not cinder_handled.is_handled_by_reviewers
    # under the sla
    under_sla = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(job_id=2),
        location=AbuseReport.LOCATION.ADDON,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert under_sla.is_handled_by_reviewers
    # over the sla
    over_sla = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(job_id=3, created=just_over_three_days_ago),
        location=AbuseReport.LOCATION.ADDON,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert over_sla.is_handled_by_reviewers
    # over, but resolved already
    resolved = AbuseReport.objects.create(
        cinder_job=CinderJob.objects.create(
            job_id=4,
            created=just_over_three_days_ago,
            decision_action=CinderJob.DECISION_ACTIONS.AMO_DISABLE_ADDON,
        ),
        location=AbuseReport.LOCATION.ADDON,
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
    )
    assert resolved.is_handled_by_reviewers
    assert list(unresolved_reviewers_handled_jobs_qs()) == [over_sla.cinder_job]
