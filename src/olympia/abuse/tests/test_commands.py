import uuid
from datetime import datetime

from django.conf import settings
from django.core.management import call_command

import pytest
import responses

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.reviewers.models import NeedsHumanReview

from ..models import AbuseReport, CinderJob, CinderQueueMove, ContentDecision


@pytest.mark.django_db
def test_retry_unreported_abuse_reports():
    addon = addon_factory()
    reported_job = CinderJob.objects.create()
    reported = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
        cinder_job=reported_job,
    )
    unreported = AbuseReport.objects.create(
        guid=addon.guid, reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE
    )
    notactionable = AbuseReport.objects.create(
        guid=addon.guid, reason=AbuseReport.REASONS.FEEDBACK_SPAM
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '1234-xyz'},
        status=201,
    )

    call_command('retry_unreported_abuse_reports')

    assert reported.reload().cinder_job == reported_job  # not changed
    assert unreported.reload().cinder_job is not None
    assert unreported.cinder_job.job_id == '1234-xyz'
    assert notactionable.reload().cinder_job is None
    assert len(responses.calls) == 1


class TestAutoResolveReports(TestCase):
    def setUp(self):
        user_factory(id=settings.TASK_USER_ID)

    def test_auto_resolve_reviewed_handled(self):
        addon1 = addon_factory(version_kw={'human_review_date': datetime.now()})
        job1 = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=addon1
        )
        AbuseReport.objects.create(
            guid=addon1.guid,
            cinder_job=job1,
        )
        unreviewed = version_factory(
            addon=addon1, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        job_not_reviewed = CinderJob.objects.create(
            job_id='nope', resolvable_in_reviewer_tools=True, target_addon=addon1
        )
        AbuseReport.objects.create(
            guid=addon1.guid,
            addon_version=unreviewed.version,
            cinder_job=job_not_reviewed,
        )
        addon2 = addon_factory(version_kw={'human_review_date': datetime.now()})
        job2 = CinderJob.objects.create(
            job_id='2', resolvable_in_reviewer_tools=True, target_addon=addon2
        )
        AbuseReport.objects.create(
            guid=addon2.guid,
            addon_version=addon2.current_version.version,
            cinder_job=job2,
        )
        assert CinderJob.objects.unresolved().count() == 3
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job1.job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job2.job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            version=unreviewed,
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            version=addon2.current_version,
        )
        call_command('auto_resolve_reports')

        assert CinderJob.objects.unresolved().count() == 1
        assert CinderJob.objects.unresolved().get() == job_not_reviewed
        assert job1.reload().decision
        assert job1.decision.action == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        assert job2.reload().decision
        assert job2.decision.action == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        # NHRs should be cleared.
        assert not NeedsHumanReview.objects.filter(
            version__addon=addon1, is_active=True
        ).exists()
        assert not NeedsHumanReview.objects.filter(
            version__addon=addon2, is_active=True
        ).exists()

    def test_auto_resolve_forwarded_job(self):
        addon1 = addon_factory(version_kw={'human_review_date': datetime.now()})
        job_forwarded = CinderJob.objects.create(
            job_id='forwarded', resolvable_in_reviewer_tools=True, target_addon=addon1
        )
        AbuseReport.objects.create(
            guid=addon1.guid,
            cinder_job=job_forwarded,
        )
        CinderQueueMove.objects.create(cinder_job=job_forwarded)

        addon2 = addon_factory(version_kw={'human_review_date': datetime.now()})
        job_legal_reason = CinderJob.objects.create(
            job_id='legal', resolvable_in_reviewer_tools=True, target_addon=addon2
        )
        AbuseReport.objects.create(
            guid=addon2.guid,
            cinder_job=job_legal_reason,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        CinderQueueMove.objects.create(cinder_job=job_legal_reason)

        addon3 = addon_factory(version_kw={'human_review_date': datetime.now()})
        job_appeal = CinderJob.objects.create(
            job_id='appeal', resolvable_in_reviewer_tools=True, target_addon=addon3
        )
        job_appealed = CinderJob.objects.create(
            job_id='appealled',
            decision=ContentDecision.objects.create(
                addon=addon3,
                action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
                appeal_job=job_appeal,
            ),
        )
        AbuseReport.objects.create(
            guid=addon3.guid,
            cinder_job=job_appealed,
        )
        CinderQueueMove.objects.create(cinder_job=job_appeal)

        assert CinderJob.objects.unresolved().count() == 3
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job_forwarded.job_id}/decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION,
            version=addon1.current_version,
        )

        call_command('auto_resolve_reports')

        assert CinderJob.objects.unresolved().count() == 2
        assert list(CinderJob.objects.unresolved().all()) == [
            job_legal_reason,
            job_appeal,
        ]
        assert job_forwarded.reload().decision
        assert job_forwarded.decision.action == DECISION_ACTIONS.AMO_CLOSED_NO_ACTION
        # NHR should be cleared.
        assert not NeedsHumanReview.objects.filter(
            version__addon=addon1, is_active=True
        ).exists()
