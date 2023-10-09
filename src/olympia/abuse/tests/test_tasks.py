import json
from datetime import datetime

from django.conf import settings

import pytest
import responses
from freezegun import freeze_time

from olympia import amo
from olympia.abuse.tasks import flag_high_abuse_reports_addons_according_to_review_tier
from olympia.amo.tests import addon_factory, days_ago, user_factory
from olympia.constants.reviewers import EXTRA_REVIEW_TARGET_PER_DAY_CONFIG_KEY
from olympia.files.models import File
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.versions.models import Version
from olympia.zadmin.models import set_config

from ..models import AbuseReport, CinderReport
from ..tasks import appeal_to_cinder, report_to_cinder


def addon_factory_with_abuse_reports(*args, **kwargs):
    abuse_reports_count = kwargs.pop('abuse_reports_count')
    addon = addon_factory(*args, **kwargs)
    for _x in range(0, abuse_reports_count):
        AbuseReport.objects.create(guid=addon.guid)
    return addon


@freeze_time('2023-06-26 11:00')
@pytest.mark.django_db
def test_flag_high_abuse_reports_addons_according_to_review_tier():
    user_factory(pk=settings.TASK_USER_ID)
    set_config(EXTRA_REVIEW_TARGET_PER_DAY_CONFIG_KEY, '1')
    # Create some usage tiers and add add-ons in them for the task to do
    # something. The ones missing a lower, upper, or abuse report threshold
    # don't do anything for this test.
    UsageTier.objects.create(name='Not a tier with usage values')
    UsageTier.objects.create(
        name='C tier (no abuse threshold)',
        lower_adu_threshold=100,
        upper_adu_threshold=200,
    )
    UsageTier.objects.create(
        name='B tier',
        lower_adu_threshold=200,
        upper_adu_threshold=250,
        abuse_reports_ratio_threshold_before_flagging=1,
    )
    UsageTier.objects.create(
        name='A tier',
        lower_adu_threshold=250,
        upper_adu_threshold=1000,
        abuse_reports_ratio_threshold_before_flagging=2,
    )
    UsageTier.objects.create(
        name='S tier (no upper threshold)',
        lower_adu_threshold=1000,
        upper_adu_threshold=None,
        abuse_reports_ratio_threshold_before_flagging=1,
    )

    not_flagged = [
        # Belongs to C tier, which doesn't have a growth threshold set.
        addon_factory_with_abuse_reports(
            name='C tier addon', average_daily_users=100, abuse_reports_count=2
        ),
        # Belongs to B tier but not an extension.
        addon_factory_with_abuse_reports(
            name='B tier language pack',
            type=amo.ADDON_LPAPP,
            average_daily_users=200,
            abuse_reports_count=3,
        ),
        addon_factory_with_abuse_reports(
            name='B tier theme',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=200,
            abuse_reports_count=3,
        ),
        # Belongs to A tier but will be below the abuse threshold.
        addon_factory_with_abuse_reports(
            name='A tier below threshold',
            average_daily_users=250,
            abuse_reports_count=2,
        ),
        # Belongs to S tier, which doesn't have an upper threshold. (like
        # notable, subject to human review anyway)
        addon_factory_with_abuse_reports(
            name='S tier addon', average_daily_users=1000, abuse_reports_count=10
        ),
        # Belongs to A tier but already human reviewed.
        addon_factory_with_abuse_reports(
            name='A tier already reviewed',
            average_daily_users=250,
            version_kw={'human_review_date': datetime.now()},
            abuse_reports_count=3,
        ),
        # Belongs to B tier but already disabled.
        addon_factory_with_abuse_reports(
            name='B tier already disabled',
            average_daily_users=200,
            status=amo.STATUS_DISABLED,
            abuse_reports_count=3,
        ),
        # Belongs to B tier but already flagged for human review
        NeedsHumanReview.objects.create(
            version=addon_factory_with_abuse_reports(
                name='B tier already flagged',
                average_daily_users=200,
                abuse_reports_count=3,
            ).current_version,
            is_active=True,
        ).version.addon,
        # Belongs to B tier but the last abuse report that would make its total
        # above threshold is deleted, and it has another old one that does not
        # count (see below).
        addon_factory_with_abuse_reports(
            name='B tier deleted and old reports',
            average_daily_users=200,
            abuse_reports_count=2,
        ),
    ]
    AbuseReport.objects.filter(guid=not_flagged[-1].guid).latest('pk').delete()
    AbuseReport.objects.create(guid=not_flagged[-1].guid, created=days_ago(15))

    flagged = [
        addon_factory_with_abuse_reports(
            name='B tier', average_daily_users=200, abuse_reports_count=2
        ),
        addon_factory_with_abuse_reports(
            name='A tier', average_daily_users=250, abuse_reports_count=6
        ),
        NeedsHumanReview.objects.create(
            version=addon_factory_with_abuse_reports(
                name='A tier with inactive flags',
                average_daily_users=250,
                abuse_reports_count=6,
            ).current_version,
            is_active=False,
        ).version.addon,
        addon_factory_with_abuse_reports(
            name='B tier with a report a week old',
            average_daily_users=200,
            abuse_reports_count=2,
        ),
    ]
    # Still exactly (to the second) within the window we care about.
    AbuseReport.objects.filter(guid=flagged[-1].guid).update(created=days_ago(14))

    # Pretend all files were signed otherwise they would not get flagged.
    File.objects.update(is_signed=True)
    flag_high_abuse_reports_addons_according_to_review_tier()

    for addon in not_flagged:
        assert (
            addon.versions.latest('pk')
            .needshumanreview_set.filter(
                reason=NeedsHumanReview.REASON_ABUSE_REPORTS_THRESHOLD, is_active=True
            )
            .count()
            == 0
        ), f'Addon {addon} should not have been flagged'

    for addon in flagged:
        version = addon.versions.latest('pk')
        assert (
            version.needshumanreview_set.filter(
                reason=NeedsHumanReview.REASON_ABUSE_REPORTS_THRESHOLD, is_active=True
            ).count()
            == 1
        ), f'Addon {addon} should have been flagged'

    # We've set EXTRA_REVIEW_TARGET_PER_DAY_CONFIG_KEY so that there would be
    # one review per day after . Since we've frozen time on a Wednesday,
    # we should get: Friday, Monday (skipping week-end), Tuesday.
    due_dates = (
        Version.objects.filter(addon__in=flagged)
        .values_list('due_date', flat=True)
        .order_by('due_date')
    )
    assert list(due_dates) == [
        datetime(2023, 6, 29, 11, 0),
        datetime(2023, 6, 30, 11, 0),
        datetime(2023, 7, 3, 11, 0),
        datetime(2023, 7, 4, 11, 0),
    ]


@pytest.mark.django_db
def test_addon_report_to_cinder():
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid, reason=AbuseReport.REASONS.CSAM, message='This is bad'
    )
    assert not CinderReport.objects.exists()
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '1234-xyz'},
        status=201,
    )

    report_to_cinder.delay(abuse_report.id)

    request = responses.calls[0].request
    assert request.headers['authorization'] == 'Bearer fake-test-token'
    assert json.loads(request.body) == {
        'context': {'entities': [], 'relationships': []},
        'entity': {
            'guid': addon.guid,
            'id': str(addon.pk),
            'name': str(addon.name),
            'slug': addon.slug,
        },
        'entity_type': 'amo_addon',
        'queue_slug': 'amo-content-infringement',
        'reasoning': 'This is bad',
    }

    assert CinderReport.objects.count() == 1
    cinder_report = CinderReport.objects.get()
    assert cinder_report.abuse_report == abuse_report
    assert cinder_report.job_id == '1234-xyz'


@pytest.mark.django_db
def test_addon_appeal_to_cinder():
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.CSAM,
        reporter_name='It is me',
        reporter_email='m@r.io',
    )
    cinder_report = CinderReport.objects.create(
        abuse_report=abuse_report,
        decision_id='4815162342-abc',
        decision_date=datetime.now(),
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}appeal',
        json={'external_id': '2432615184-xyz'},
        status=201,
    )

    appeal_to_cinder.delay(
        decision_id='4815162342-abc', appeal_text='I appeal', user_id=None
    )

    request = responses.calls[0].request
    assert request.headers['authorization'] == 'Bearer fake-test-token'
    assert json.loads(request.body) == {
        'appealer_entity': {
            'email': 'm@r.io',
            'id': 'It is me : m@r.io',
            'name': 'It is me',
        },
        'appealer_entity_type': 'amo_unauthenticated_reporter',
        'decision_to_appeal_id': '4815162342-abc',
        'queue_slug': 'amo-content-infringement',
        'reasoning': 'I appeal',
    }

    cinder_report = CinderReport.objects.get()
    assert cinder_report.appeal_id == '2432615184-xyz'


@pytest.mark.django_db
def test_addon_appeal_to_cinder_authenticated():
    user = user_factory(fxa_id='fake-fxa-id')
    addon = addon_factory(users=[user])
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.CSAM,
    )
    cinder_report = CinderReport.objects.create(
        abuse_report=abuse_report,
        decision_id='4815162342-abc',
        decision_date=datetime.now(),
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}appeal',
        json={'external_id': '2432615184-xyz'},
        status=201,
    )

    appeal_to_cinder.delay(
        decision_id='4815162342-abc', appeal_text='I appeal', user_id=user.pk
    )

    request = responses.calls[0].request
    assert request.headers['authorization'] == 'Bearer fake-test-token'
    assert json.loads(request.body) == {
        'appealer_entity': {
            'email': user.email,
            'id': str(user.pk),
            'name': '',
            'fxa_id': user.fxa_id,
        },
        'appealer_entity_type': 'amo_user',
        'decision_to_appeal_id': '4815162342-abc',
        'queue_slug': 'amo-content-infringement',
        'reasoning': 'I appeal',
    }

    cinder_report = CinderReport.objects.get()
    assert cinder_report.appeal_id == '2432615184-xyz'
