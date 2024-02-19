from django.core.management import call_command

from olympia.abuse.models import AbuseReport, CinderJob
from olympia.amo.tests import TestCase, addon_factory, user_factory


class TestFillCinderJob(TestCase):
    def test_fill_somehow_no_abuse_reports(self):
        job = CinderJob.objects.create(job_id='job123')

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert not job.target_addon
        assert not job.resolvable_in_reviewer_tools

    def test_fill_addon(self):
        addon_factory()  # Extra add-on, shouldn't matter.
        addon = addon_factory()
        job = CinderJob.objects.create(job_id='job123')
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert job.target_addon == report.target == addon
        assert not job.resolvable_in_reviewer_tools

    def test_fill_appealed_job(self):
        addon_factory()  # Extra add-on, shouldn't matter.
        addon = addon_factory()
        job = CinderJob.objects.create(
            job_id='job123', appeal_job=CinderJob.objects.create(job_id='appeal123')
        )
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert job.target_addon == report.target == addon
        assert not job.resolvable_in_reviewer_tools
        job.appeal_job.reload()
        assert job.appeal_job.target_addon == report.target == addon
        assert not job.appeal_job.resolvable_in_reviewer_tools

    def test_fill_non_addon(self):
        user = user_factory()
        job = CinderJob.objects.create(job_id='job123')
        AbuseReport.objects.create(user=user, cinder_job=job)

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert job.target_addon is None
        assert not job.resolvable_in_reviewer_tools

    def test_fill_resolvable_in_reviewer_tools(self):
        addon_factory()  # Extra add-on, shouldn't matter.
        addon = addon_factory()
        job = CinderJob.objects.create(job_id='job123')
        report = AbuseReport.objects.create(
            guid=addon.guid,
            cinder_job=job,
            location=AbuseReport.LOCATION.BOTH,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
        )

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert job.target_addon == report.target == addon
        assert job.resolvable_in_reviewer_tools

    def test_fill_not_resolvable_in_reviewer_tools(self):
        addon_factory()  # Extra add-on, shouldn't matter.
        addon = addon_factory()
        job = CinderJob.objects.create(job_id='job123')
        # Location makes it not resolvable in reviewer tools unless escalated
        # even though the reason is policy violation.
        report = AbuseReport.objects.create(
            guid=addon.guid,
            cinder_job=job,
            location=AbuseReport.LOCATION.AMO,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
        )

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert job.target_addon == report.target == addon
        assert not job.resolvable_in_reviewer_tools

    def test_fill_escalated_addon(self):
        addon_factory()  # Extra add-on, shouldn't matter.
        addon = addon_factory()
        job = CinderJob.objects.create(
            job_id='job123',
            decision_action=CinderJob.DECISION_ACTIONS.AMO_ESCALATE_ADDON,
        )
        report = AbuseReport.objects.create(guid=addon.guid, cinder_job=job)

        call_command('fill_cinderjobs_denormalized_fields')

        job.reload()
        assert job.target_addon == report.target == addon
        assert job.resolvable_in_reviewer_tools
