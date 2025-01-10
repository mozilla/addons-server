from django.conf import settings
from django.core.management import call_command

import pytest
import responses

from olympia.amo.tests import addon_factory, user_factory
from olympia.constants.abuse import DECISION_ACTIONS

from ..models import AbuseReport, CinderJob, ContentDecision


@pytest.mark.django_db
def test_backfill_cinder_escalations():
    user = user_factory(pk=settings.TASK_USER_ID)
    addon = addon_factory(users=[user])
    job_with_reports = CinderJob.objects.create(
        job_id='1',
        decision=ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon
        ),
    )
    abuse = AbuseReport.objects.create(guid=addon.guid, cinder_job=job_with_reports)
    appeal_job = CinderJob.objects.create(
        job_id='2',
        decision=ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon
        ),
    )
    appealled_decision = ContentDecision.objects.create(
        action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon, appeal_job=appeal_job
    )

    # And some jobs/decisions that should be skipped:
    # decision that wasn't an escalation (or isn't any longer)
    CinderJob.objects.create(
        job_id='3',
        decision=ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE, addon=addon
        ),
    )
    # decision without an associated cinder job (shouldn't occur, but its handled)
    ContentDecision.objects.create(
        action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon
    )
    # decision that already has a forwarded job created, so we don't need to backfill
    CinderJob.objects.create(
        job_id='4',
        decision=ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_ESCALATE_ADDON, addon=addon
        ),
        forwarded_to_job=CinderJob.objects.create(job_id='5'),
    )
    assert CinderJob.objects.count() == 5
    assert ContentDecision.objects.count() == 6
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '6'},
        status=201,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '7'},
        status=201,
    )

    call_command('backfill_cinder_escalations')
    assert CinderJob.objects.count() == 7
    assert ContentDecision.objects.count() == 6

    new_job_with_reports = job_with_reports.reload().forwarded_to_job
    assert new_job_with_reports
    assert new_job_with_reports.resolvable_in_reviewer_tools is True
    assert abuse.reload().cinder_job == new_job_with_reports
    new_appeal_job = appeal_job.reload().forwarded_to_job
    assert new_appeal_job
    assert new_appeal_job.resolvable_in_reviewer_tools is True
    assert appealled_decision.reload().appeal_job == new_appeal_job
