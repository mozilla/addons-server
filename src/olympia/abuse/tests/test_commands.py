from django.conf import settings
from django.core.management import call_command

import pytest
import responses

from olympia.amo.tests import addon_factory

from ..models import AbuseReport, CinderJob


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
