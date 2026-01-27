import json
import uuid
from datetime import datetime
from unittest import mock

from django.conf import settings

import pytest
import requests
import responses
import time_machine
from celery.exceptions import Retry

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, days_ago, user_factory
from olympia.constants.abuse import (
    DECISION_ACTIONS,
    ILLEGAL_CATEGORIES,
    ILLEGAL_SUBCATEGORIES,
)
from olympia.files.models import File
from olympia.reviewers.models import NeedsHumanReview, ReviewActionReason, UsageTier
from olympia.versions.models import Version
from olympia.zadmin.models import set_config

from ..cinder import CinderAddon
from ..models import AbuseReport, CinderJob, CinderPolicy, ContentDecision
from ..tasks import (
    appeal_to_cinder,
    flag_high_abuse_reports_addons_according_to_review_tier,
    report_decision_to_cinder_and_notify,
    report_to_cinder,
    sync_cinder_policies,
)


def addon_factory_with_abuse_reports(*, abuse_reports_count, **kwargs):
    abuse_kwargs = kwargs.pop('abuse_reports_kwargs', {})
    addon = addon_factory(**kwargs)
    for _x in range(0, abuse_reports_count):
        AbuseReport.objects.create(guid=addon.guid, **abuse_kwargs)
    return addon


def _high_abuse_reports_setup(field):
    user_factory(pk=settings.TASK_USER_ID)
    # Create some usage tiers and add add-ons in them for the task to do
    # something. The ones missing a lower, upper, or abuse report threshold
    # don't do anything for this test.
    UsageTier.objects.create(name='Not a tier with usage values')
    UsageTier.objects.create(
        name='D tier (no lower threshold)',
        upper_adu_threshold=100,
        **{field: 200},
    )
    UsageTier.objects.create(
        name='C tier (no abuse threshold)',
        lower_adu_threshold=100,
        upper_adu_threshold=200,
    )
    UsageTier.objects.create(
        name='B tier',
        lower_adu_threshold=200,
        upper_adu_threshold=250,
        **{field: 1},
    )
    UsageTier.objects.create(
        name='A tier',
        lower_adu_threshold=250,
        upper_adu_threshold=1000,
        **{field: 2},
    )
    UsageTier.objects.create(
        name='S tier (no upper threshold)',
        lower_adu_threshold=1000,
        upper_adu_threshold=None,
        **{field: 1},
    )

    not_flagged = [
        # Belongs to D tier, below threshold since it has 0 reports/users.
        addon_factory(name='D tier empty addon', average_daily_users=0),
        # Belongs to D tier, below threshold since it has 1 report and 0 users.
        addon_factory_with_abuse_reports(
            name='D tier addon below threshold',
            average_daily_users=0,
            abuse_reports_count=1,
        ),
        # Belongs to C tier, which doesn't have an abuse report threshold set.
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
        # only has reports that are individually actionable, so ignored
        addon_factory_with_abuse_reports(
            name='B tier, but all dsa reasons',
            average_daily_users=200,
            abuse_reports_count=2,
            abuse_reports_kwargs={
                'reason': AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE
            },
        ),
        # Would be above the threshold, but has one report that is individually
        # actionable so just below
        addon_factory_with_abuse_reports(
            name='A tier, but one report a dsa reason, for a listed version',
            average_daily_users=250,
            abuse_reports_count=3,
        ),
        # Belongs to B tier but the last abuse report that would make its total
        # above threshold is deleted, and it has another old one that does not
        # count (see below).
        addon_factory_with_abuse_reports(
            name='B tier deleted and old reports',
            average_daily_users=200,
            abuse_reports_count=2,
        ),
    ]
    with_deleted_report = not_flagged[-1]
    AbuseReport.objects.filter(guid=with_deleted_report.guid).latest('pk').delete()
    AbuseReport.objects.create(guid=with_deleted_report.guid, created=days_ago(15))
    with_dsa_report = not_flagged[-2]
    AbuseReport.objects.filter(guid=with_dsa_report.guid).latest('pk').update(
        addon_version=with_dsa_report.current_version.version,
        reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
    )

    flagged = [
        addon_factory_with_abuse_reports(
            name='D tier addon with reports',
            average_daily_users=0,
            abuse_reports_count=2,
        ),
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

    return not_flagged, flagged


@time_machine.travel('2023-06-26 11:00', tick=False)
@pytest.mark.django_db
def test_flag_high_abuse_reports_addons_according_to_review_tier():
    set_config(amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY, '1')
    not_flagged, flagged = _high_abuse_reports_setup(
        'abuse_reports_ratio_threshold_before_flagging'
    )
    not_flagged.append(
        # Belongs to B tier but already flagged for human review
        NeedsHumanReview.objects.create(
            version=addon_factory_with_abuse_reports(
                name='B tier already flagged',
                average_daily_users=200,
                abuse_reports_count=3,
            ).current_version,
            is_active=True,
        ).version.addon
    )
    # Pretend all files were signed otherwise they would not get flagged.
    File.objects.update(is_signed=True)

    flag_high_abuse_reports_addons_according_to_review_tier()

    for addon in not_flagged:
        assert (
            addon.versions.latest('pk')
            .needshumanreview_set.filter(
                reason=NeedsHumanReview.REASONS.ABUSE_REPORTS_THRESHOLD, is_active=True
            )
            .count()
            == 0
        ), f'Addon {addon} should not have been flagged'

    for addon in flagged:
        version = addon.versions.latest('pk')
        assert (
            version.needshumanreview_set.filter(
                reason=NeedsHumanReview.REASONS.ABUSE_REPORTS_THRESHOLD, is_active=True
            ).count()
            == 1
        ), f'Addon {addon} should have been flagged'

    # We've set amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY so that there would be
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
        datetime(2023, 7, 5, 11, 0),
    ]


@time_machine.travel('2023-06-26 11:00', tick=False)
@pytest.mark.django_db
def test_block_high_abuse_reports_addons_according_to_review_tier():
    not_blocked, blocked = _high_abuse_reports_setup(
        'abuse_reports_ratio_threshold_before_blocking'
    )
    responses.add_callback(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
    )

    flag_high_abuse_reports_addons_according_to_review_tier()

    for addon in not_blocked:
        addon.reload()
        assert not addon.block, f'Addon {addon} should not have been blocked'

    for addon in blocked:
        addon.reload()
        assert addon.status == amo.STATUS_DISABLED, (
            f'Addon {addon} should have been disabled'
        )
        assert addon.block, f'Addon {addon} should have have a block record'
        assert (
            not addon.versions(manager='unfiltered_for_relations')
            .filter(blockversion__isnull=True)
            .exists()
        ), f'Addon {addon}s versions should have been blocked'
        assert (
            ActivityLog.objects.filter(
                addonlog__addon=addon, action=amo.LOG.FORCE_DISABLE.id
            )
            .get()
            .details['reason']
            == 'Rejected and blocked due to: high abuse report count'
        )


@pytest.mark.django_db
@mock.patch('olympia.abuse.tasks.statsd.incr')
def test_addon_report_to_cinder(statsd_incr_mock):
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        message='This is bad',
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    assert not CinderJob.objects.exists()
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '1234-xyz'},
        status=201,
    )
    statsd_incr_mock.reset_mock()

    report_to_cinder.delay(abuse_report.id)

    request = responses.calls[0].request
    assert request.headers['authorization'] == 'Bearer fake-test-token'
    assert json.loads(request.body) == {
        'context': {
            'entities': [
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': 'This is bad',
                        'reason': 'DSA: It violates the law '
                        'or contains content that '
                        'violates the law',
                        'considers_illegal': True,
                        'illegal_category': 'STATEMENT_CATEGORY_OTHER',
                        'illegal_subcategory': 'KEYWORD_OTHER',
                    },
                    'entity_type': 'amo_report',
                }
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                }
            ],
        },
        'entity': {
            'id': str(addon.id),
            'average_daily_users': addon.average_daily_users,
            'created': str(addon.created),
            'description': '',
            'guid': addon.guid,
            'homepage': None,
            'last_updated': str(addon.last_updated),
            'name': str(addon.name),
            'release_notes': '',
            'privacy_policy': '',
            'promoted': '',
            'requires_payment': False,
            'slug': addon.slug,
            'summary': str(addon.summary),
            'support_email': None,
            'support_url': None,
            'version': str(addon.current_version.version),
        },
        'entity_type': 'amo_addon',
        'queue_slug': 'amo-env-listings',
        'reasoning': 'This is bad',
    }

    assert CinderJob.objects.count() == 1
    cinder_job = CinderJob.objects.get()
    assert abuse_report.reload().cinder_job == cinder_job
    assert cinder_job.job_id == '1234-xyz'

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == ('abuse.tasks.report_to_cinder.success',)


@pytest.mark.django_db
@mock.patch('olympia.abuse.tasks.statsd.incr')
@mock.patch('olympia.abuse.tasks.log.exception')
def test_addon_report_to_cinder_exception(log_exception_mock, statsd_incr_mock):
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        message='This is bad',
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    assert not CinderJob.objects.exists()
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '1234-xyz'},
        status=500,
    )
    statsd_incr_mock.reset_mock()

    with pytest.raises(Retry) as exc_info:
        report_to_cinder.delay(abuse_report.id)
    exception = exc_info.value
    assert exception.when == 30
    assert log_exception_mock.call_count == 1
    assert log_exception_mock.call_args_list == [
        (
            ('Retrying Celery Task report_to_cinder',),
            {'exc_info': exception.exc},
        ),
    ]

    assert CinderJob.objects.count() == 0

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == ('abuse.tasks.report_to_cinder.failure',)


@pytest.mark.django_db
@mock.patch('olympia.abuse.tasks.log.exception')
def test_multiple_retries_with_exceptions_on_first_and_seventh_retry(
    log_exception_mock,
):
    addon = addon_factory()
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        message='This is bad',
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '1234-xyz'},
        status=500,
    )

    with mock.patch('celery.app.task.Task.request') as request_mock:
        for i in range(10):
            with pytest.raises(requests.exceptions.HTTPError):
                # Simulate Celery state: how many retries have *already happened*.
                request_mock.retries = i
                report_to_cinder.run(abuse_report.id)

    assert log_exception_mock.call_count == 2
    assert log_exception_mock.call_args_list == [
        mock.call('Retrying Celery Task report_to_cinder', exc_info=mock.ANY),
        mock.call(
            'Retried Celery Task for report_to_cinder 7 times', exc_info=mock.ANY
        ),
    ]

    assert CinderJob.objects.count() == 0


@pytest.mark.django_db
def test_addon_report_to_cinder_different_locale():
    names = {
        'fr': 'French näme',
        'en-US': 'English näme',
    }
    addon = addon_factory(name=names, slug='my-addon', default_locale='en-US')
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        message='This is bad',
        application_locale='fr',
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    assert not CinderJob.objects.exists()
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
        'context': {
            'entities': [
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': 'fr',
                        'message': 'This is bad',
                        'reason': 'DSA: It violates the law '
                        'or contains content that '
                        'violates the law',
                        'considers_illegal': True,
                        'illegal_category': 'STATEMENT_CATEGORY_OTHER',
                        'illegal_subcategory': 'KEYWORD_OTHER',
                    },
                    'entity_type': 'amo_report',
                }
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                }
            ],
        },
        'entity': {
            'id': str(addon.id),
            'average_daily_users': addon.average_daily_users,
            'created': str(addon.created),
            'description': '',
            'guid': addon.guid,
            'homepage': None,
            'last_updated': str(addon.last_updated),
            'name': str(names['fr']),
            'release_notes': '',
            'privacy_policy': '',
            'promoted': '',
            'requires_payment': False,
            'slug': addon.slug,
            'summary': str(addon.summary),
            'support_email': None,
            'support_url': None,
            'version': str(addon.current_version.version),
        },
        'entity_type': 'amo_addon',
        'queue_slug': 'amo-env-listings',
        'reasoning': 'This is bad',
    }

    assert CinderJob.objects.count() == 1
    cinder_job = CinderJob.objects.get()
    assert abuse_report.reload().cinder_job == cinder_job
    assert cinder_job.job_id == '1234-xyz'


@pytest.mark.django_db
@mock.patch.object(CinderAddon, 'RELATIONSHIPS_BATCH_SIZE', 1)
@mock.patch('olympia.amo.tasks.statsd.incr')
def test_addon_report_with_additional_context_no_retry(statsd_incr_mock):
    addon = addon_factory()
    addon.authors.add(user_factory())
    addon.authors.add(user_factory())

    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        message='This is bad',
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_report',
        json={'job_id': '1234-xyz'},
        status=201,
    )
    additional = responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}graph/',
        status=400,
    )
    statsd_incr_mock.reset_mock()

    # An exception in the additional context shouldn't trigger a Retry
    with pytest.raises(ConnectionError):
        report_to_cinder.delay(abuse_report.id)

    assert len(responses.calls) == 2
    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == ('abuse.tasks.report_to_cinder.failure',)
    assert additional.call_count == 1


@pytest.mark.django_db
@mock.patch('olympia.abuse.tasks.statsd.incr')
def test_addon_appeal_to_cinder_reporter(statsd_incr_mock):
    addon = addon_factory()
    cinder_job = CinderJob.objects.create(
        decision=ContentDecision.objects.create(
            cinder_id='4815162342-abc',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=addon,
            action_date=datetime.now(),
        )
    )
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        reporter_name='It is me',
        reporter_email='m@r.io',
        cinder_job=cinder_job,
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}appeal',
        json={'external_id': '2432615184-xyz'},
        status=201,
    )
    statsd_incr_mock.reset_mock()

    appeal_to_cinder.delay(
        decision_cinder_id=cinder_job.decision.cinder_id,
        abuse_report_id=abuse_report.id,
        appeal_text='I appeal',
        user_id=None,
        is_reporter=True,
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
        'queue_slug': 'amo-env-listings',
        'reasoning': 'I appeal',
    }

    cinder_job.reload()
    assert cinder_job.decision.appeal_job_id
    appeal_job = cinder_job.decision.appeal_job
    assert appeal_job.job_id == '2432615184-xyz'
    abuse_report.reload()
    assert abuse_report.cinderappeal.decision == cinder_job.decision

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == ('abuse.tasks.appeal_to_cinder.success',)


@pytest.mark.django_db
@mock.patch('olympia.abuse.tasks.statsd.incr')
@mock.patch('olympia.abuse.tasks.log.exception')
def test_addon_appeal_to_cinder_reporter_exception(
    log_exception_mock, statsd_incr_mock
):
    addon = addon_factory()
    cinder_job = CinderJob.objects.create(
        decision=ContentDecision.objects.create(
            cinder_id='4815162342-abc',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=addon,
            action_date=datetime.now(),
        )
    )
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        reporter_name='It is me',
        reporter_email='m@r.io',
        cinder_job=cinder_job,
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}appeal',
        json={'external_id': '2432615184-xyz'},
        status=500,
    )
    statsd_incr_mock.reset_mock()

    with pytest.raises(Retry) as exc_info:
        appeal_to_cinder.delay(
            decision_cinder_id=cinder_job.decision.cinder_id,
            abuse_report_id=abuse_report.id,
            appeal_text='I appeal',
            user_id=None,
            is_reporter=True,
        )
    exception = exc_info.value
    assert exception.when == 30
    assert log_exception_mock.call_count == 1
    assert log_exception_mock.call_args_list == [
        (
            ('Retrying Celery Task appeal_to_cinder',),
            {'exc_info': exception.exc},
        ),
    ]

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == ('abuse.tasks.appeal_to_cinder.failure',)


@pytest.mark.django_db
def test_addon_appeal_to_cinder_authenticated_reporter():
    user = user_factory(fxa_id='fake-fxa-id')
    addon = addon_factory()
    cinder_job = CinderJob.objects.create(
        decision=ContentDecision.objects.create(
            cinder_id='4815162342-abc',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=addon,
            action_date=datetime.now(),
        )
    )
    abuse_report = AbuseReport.objects.create(
        guid=addon.guid,
        reason=AbuseReport.REASONS.ILLEGAL,
        cinder_job=cinder_job,
        reporter=user,
        illegal_category=ILLEGAL_CATEGORIES.OTHER,
        illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}appeal',
        json={'external_id': '2432615184-xyz'},
        status=201,
    )

    appeal_to_cinder.delay(
        decision_cinder_id=cinder_job.decision.cinder_id,
        abuse_report_id=abuse_report.pk,
        appeal_text='I appeal',
        user_id=user.pk,
        is_reporter=True,
    )

    request = responses.calls[0].request
    assert request.headers['authorization'] == 'Bearer fake-test-token'
    assert json.loads(request.body) == {
        'appealer_entity': {
            'created': str(user.created),
            'email': user.email,
            'fxa_id': user.fxa_id,
            'id': str(user.pk),
            'name': '',
        },
        'appealer_entity_type': 'amo_user',
        'decision_to_appeal_id': '4815162342-abc',
        'queue_slug': 'amo-env-listings',
        'reasoning': 'I appeal',
    }

    cinder_job.reload()
    assert cinder_job.decision.appeal_job_id
    appeal_job = cinder_job.decision.appeal_job
    assert appeal_job.job_id == '2432615184-xyz'
    abuse_report.reload()
    assert abuse_report.cinderappeal.decision == cinder_job.decision


@pytest.mark.django_db
def test_addon_appeal_to_cinder_authenticated_author():
    user = user_factory(fxa_id='fake-fxa-id')
    user_factory(pk=settings.TASK_USER_ID)
    addon = addon_factory(users=[user])
    decision = ContentDecision.objects.create(
        cinder_id='4815162342-abc',
        action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        addon=addon,
        action_date=datetime.now(),
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}appeal',
        json={'external_id': '2432615184-xyz'},
        status=201,
    )

    appeal_to_cinder.delay(
        decision_cinder_id=decision.cinder_id,
        abuse_report_id=None,
        appeal_text='I appeal',
        user_id=user.pk,
        is_reporter=False,
    )

    request = responses.calls[0].request
    assert request.headers['authorization'] == 'Bearer fake-test-token'
    assert json.loads(request.body) == {
        'appealer_entity': {
            'created': str(user.created),
            'email': user.email,
            'fxa_id': user.fxa_id,
            'id': str(user.pk),
            'name': '',
        },
        'appealer_entity_type': 'amo_user',
        'decision_to_appeal_id': '4815162342-abc',
        'queue_slug': 'amo-env-addon-infringement',
        'reasoning': 'I appeal',
    }

    decision.reload()
    assert decision.appeal_job_id
    appeal_job = decision.appeal_job
    assert appeal_job.job_id == '2432615184-xyz'


@pytest.mark.django_db
def test_report_decision_to_cinder_and_notify_with_job():
    cinder_job = CinderJob.objects.create(job_id='999')
    abuse_report = AbuseReport.objects.create(
        guid=addon_factory().guid,
        reason=AbuseReport.REASONS.POLICY_VIOLATION,
        location=AbuseReport.LOCATION.AMO,
        cinder_job=cinder_job,
    )
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}jobs/{cinder_job.job_id}/decision',
        json={'uuid': uuid.uuid4().hex},
        status=201,
    )

    cinder_policy = CinderPolicy.objects.create(name='policy', uuid='12345678')
    decision = ContentDecision.objects.create(
        addon=abuse_report.addon,
        action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        action_date=datetime.now(),
        reasoning='some review text',
        cinder_job=cinder_job,
    )
    decision.policies.add(cinder_policy)
    ActivityLog.objects.create(
        amo.LOG.FORCE_DISABLE,
        decision.addon,
        decision.addon.current_version,
        decision,
        cinder_policy,
        details={'comments': 'some review text'},
        user=user_factory(),
    )

    with (
        mock.patch('olympia.abuse.tasks.statsd.incr') as statsd_incr_mock,
        mock.patch.object(
            ContentDecision, 'send_notifications'
        ) as send_notifications_mock,
    ):
        report_decision_to_cinder_and_notify.delay(decision_id=decision.id)

    request = responses.calls[0].request
    request_body = json.loads(request.body)
    assert request_body['policy_uuids'] == ['12345678']
    assert request_body['reasoning'] == 'some review text'
    assert 'entity' not in request_body

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == (
        'abuse.tasks.report_decision_to_cinder_and_notify.success',
    )

    assert send_notifications_mock.call_count == 1
    assert send_notifications_mock.call_args.kwargs == {'notify_owners': True}


@pytest.mark.django_db
def test_report_decision_to_cinder_and_notify():
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        json={'uuid': uuid.uuid4().hex},
        status=201,
    )
    cinder_policy = CinderPolicy.objects.create(name='policy', uuid='12345678')
    decision = ContentDecision.objects.create(
        addon=addon_factory(),
        action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        action_date=datetime.now(),
        reasoning='some review text',
    )
    decision.policies.add(cinder_policy)
    ActivityLog.objects.create(
        amo.LOG.FORCE_DISABLE,
        decision.addon,
        decision.addon.current_version,
        decision,
        cinder_policy,
        details={'comments': 'some review text'},
        user=user_factory(),
    )

    with (
        mock.patch('olympia.abuse.tasks.statsd.incr') as statsd_incr_mock,
        mock.patch.object(
            ContentDecision, 'send_notifications'
        ) as send_notifications_mock,
    ):
        report_decision_to_cinder_and_notify.delay(decision_id=decision.id)

    request = responses.calls[0].request
    request_body = json.loads(request.body)
    assert request_body['policy_uuids'] == ['12345678']
    assert request_body['reasoning'] == 'some review text'
    assert request_body['entity']['id'] == str(decision.addon_id)

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == (
        'abuse.tasks.report_decision_to_cinder_and_notify.success',
    )

    assert send_notifications_mock.call_count == 1
    assert send_notifications_mock.call_args.kwargs == {'notify_owners': True}


@pytest.mark.django_db
def test_report_decision_to_cinder_and_notify_dont_notify_owners():
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        json={'uuid': uuid.uuid4().hex},
        status=201,
    )
    cinder_policy = CinderPolicy.objects.create(name='policy', uuid='12345678')
    decision = ContentDecision.objects.create(
        addon=addon_factory(),
        action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
        action_date=datetime.now(),
        reasoning='some review text',
    )
    decision.policies.add(cinder_policy)
    ActivityLog.objects.create(
        amo.LOG.FORCE_DISABLE,
        decision.addon,
        decision.addon.current_version,
        decision,
        cinder_policy,
        details={'comments': 'some review text'},
        user=user_factory(),
    )

    with (
        mock.patch('olympia.abuse.tasks.statsd.incr') as statsd_incr_mock,
        mock.patch.object(
            ContentDecision, 'send_notifications'
        ) as send_notifications_mock,
    ):
        report_decision_to_cinder_and_notify.delay(
            decision_id=decision.id, notify_owners=False
        )

    request = responses.calls[0].request
    request_body = json.loads(request.body)
    assert request_body['policy_uuids'] == ['12345678']
    assert request_body['reasoning'] == 'some review text'
    assert request_body['entity']['id'] == str(decision.addon_id)

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == (
        'abuse.tasks.report_decision_to_cinder_and_notify.success',
    )

    assert send_notifications_mock.call_count == 1
    assert send_notifications_mock.call_args.kwargs == {'notify_owners': False}


@pytest.mark.django_db
@mock.patch('olympia.abuse.tasks.statsd.incr')
@mock.patch('olympia.abuse.tasks.log.exception')
def test_report_decision_to_cinder_and_notify_exception(
    log_exception_mock, statsd_incr_mock
):
    responses.add(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        json={'uuid': uuid.uuid4().hex},
        status=500,
    )
    decision = ContentDecision.objects.create(
        addon=addon_factory(),
        action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
        action_date=datetime.now(),
        reasoning='some review text',
    )
    statsd_incr_mock.reset_mock()

    with pytest.raises(Retry) as exc_info:
        report_decision_to_cinder_and_notify.delay(decision_id=decision.id)
    exception = exc_info.value
    assert exception.when == 30
    assert log_exception_mock.call_count == 1
    assert log_exception_mock.call_args_list == [
        (
            ('Retrying Celery Task report_decision_to_cinder_and_notify',),
            {'exc_info': exception.exc},
        ),
    ]

    assert statsd_incr_mock.call_count == 1
    assert statsd_incr_mock.call_args[0] == (
        'abuse.tasks.report_decision_to_cinder_and_notify.failure',
    )


class TestSyncCinderPolicies(TestCase):
    def setUp(self):
        self.url = f'{settings.CINDER_SERVER_URL}policies'
        self.policy = {
            'uuid': 'test-uuid',
            'name': 'test-name',
            'description': 'test-description',
            'nested_policies': [],
            'enforcement_actions': [
                {'slug': 'amo-disable-addon'},
                {'slug': 'amo-ban-user'},
            ],
        }

    def test_sync_cinder_policies_headers(self):
        responses.add(responses.GET, self.url, json=[], status=200)
        sync_cinder_policies.delay()
        assert 'Authorization' in responses.calls[0].request.headers
        assert (
            responses.calls[0].request.headers['Authorization']
            == f'Bearer {settings.CINDER_API_TOKEN}'
        )

    @mock.patch('olympia.abuse.tasks.log.exception')
    def test_sync_cinder_policies_raises_for_non_200(self, log_exception_mock):
        responses.add(responses.GET, self.url, json=[], status=500)
        with pytest.raises(Retry) as exc_info:
            sync_cinder_policies.delay()
        exception = exc_info.value
        assert exception.when == 30
        assert log_exception_mock.call_count == 1
        assert log_exception_mock.call_args_list == [
            (
                ('Retrying Celery Task sync_cinder_policies',),
                {'exc_info': exception.exc},
            ),
        ]

    def test_sync_cinder_policies_creates_new_record(self):
        responses.add(responses.GET, self.url, json=[self.policy], status=200)
        sync_cinder_policies.delay()
        assert CinderPolicy.objects.filter(uuid='test-uuid').exists()

    def test_sync_cinder_policies_updates_existing_record(self):
        CinderPolicy.objects.create(
            uuid=self.policy['uuid'],
            name=self.policy['name'],
            text=self.policy['description'],
        )

        changed_policy = {
            'name': 'new-name',
            'description': 'new-description',
            'uuid': self.policy['uuid'],
            'nested_policies': [],
        }
        responses.add(responses.GET, self.url, json=[changed_policy], status=200)

        sync_cinder_policies.delay()

        updated_policy = CinderPolicy.objects.get(uuid='test-uuid')
        assert updated_policy.name == changed_policy['name']
        assert updated_policy.text == changed_policy['description']

    def test_sync_cinder_policies_maps_fields_correctly(self):
        responses.add(responses.GET, self.url, json=[self.policy], status=200)

        sync_cinder_policies.delay()

        created_policy = CinderPolicy.objects.get(uuid=self.policy['uuid'])
        assert created_policy.name == self.policy['name']
        assert created_policy.text == self.policy['description']

    def test_sync_cinder_policies_handles_nested_policies(self):
        nested_policy = self.policy.copy()
        self.policy['nested_policies'] = [nested_policy]
        responses.add(responses.GET, self.url, json=[self.policy], status=200)

        sync_cinder_policies.delay()

        nested_policy = CinderPolicy.objects.get(uuid=nested_policy['uuid'])
        assert (
            CinderPolicy.objects.get(id=nested_policy.parent_id).uuid
            == self.policy['uuid']
        )

    def test_sync_cinder_policies_name_too_long(self):
        policies = [
            {
                'name': 'a' * 300,
                'description': 'Some description',
                'uuid': 'some-uuid',
                'nested_policies': [],
            },
            {
                'name': 'Another Pôlicy',
                'description': 'Another description',
                'uuid': 'another-uuid',
                'nested_policies': [],
            },
        ]
        responses.add(responses.GET, self.url, json=policies, status=200)

        sync_cinder_policies.delay()

        new_policy = CinderPolicy.objects.get(uuid='some-uuid')
        assert new_policy.name == 'a' * 255  # Truncated.
        assert new_policy.text == 'Some description'

        another_policy = CinderPolicy.objects.get(uuid='another-uuid')
        assert another_policy.name == 'Another Pôlicy'
        assert another_policy.text == 'Another description'

    def test_old_unused_policies_deleted_and_used_kept_and_marked_as_orphaned(self):
        CinderPolicy.objects.create(
            uuid='old-uuid',
            name='old',
            text='Old policy with no decisions or reasons',
        )
        old_policy_with_decision = CinderPolicy.objects.create(
            uuid='old-uuid-decision',
            name='old-decision',
            text='Old policy, but with linked decision',
        )
        old_policy_with_decision.update(modified=days_ago(1))
        decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE, addon=addon_factory()
        )
        decision.policies.add(old_policy_with_decision)
        old_policy_with_reason = CinderPolicy.objects.create(
            uuid='old-uuid-reason',
            name='old-reason',
            text='Old policy, but with linked ReviewActionReason',
        )
        old_policy_with_reason.update(modified=days_ago(1))
        ReviewActionReason.objects.create(
            name='a review reason',
            cinder_policy=old_policy_with_reason,
            canned_response='.',
        )
        existing_policy_exposed = CinderPolicy.objects.create(
            uuid='existing-uuid-exposed',
            name='Existing policy',
            text='Existing policy with no decision or ReviewActionReason but exposed',
            expose_in_reviewer_tools=True,
        )
        updated_policy = CinderPolicy.objects.create(
            uuid=self.policy['uuid'],
            name=self.policy['name'],
            text='Existing policy with no decision or ReviewActionReason but updated',
        )
        responses.add(responses.GET, self.url, json=[self.policy], status=200)

        sync_cinder_policies.delay()
        assert CinderPolicy.objects.filter(uuid='test-uuid').exists()
        assert updated_policy.reload().present_in_cinder is True

        assert CinderPolicy.objects.filter(uuid='old-uuid-decision').exists()
        assert old_policy_with_decision.reload().present_in_cinder is False

        assert CinderPolicy.objects.filter(uuid='old-uuid-reason').exists()
        assert old_policy_with_reason.reload().present_in_cinder is False

        assert CinderPolicy.objects.filter(uuid='existing-uuid-exposed').exists()
        assert existing_policy_exposed.reload().present_in_cinder is False

        assert not CinderPolicy.objects.filter(uuid='old-uuid').exists()

    def test_nested_policies_considered_for_deletion_and_marking_orphans(self):
        self.policy = {
            'uuid': 'test-uuid',
            'name': 'test-name',
            'description': 'test-description',
            'nested_policies': [
                {
                    'uuid': 'test-uuid-nested',
                    'name': 'test-name-nested',
                    'description': 'test-description-nested',
                    'nested_policies': [],
                }
            ],
        }
        updated_nested_policy = CinderPolicy.objects.create(
            uuid='test-uuid-nested',
            name='test-name-nested',
            text='nested policy synced from cinder',
        )
        responses.add(responses.GET, self.url, json=[self.policy], status=200)

        sync_cinder_policies.delay()
        assert CinderPolicy.objects.filter(uuid='test-uuid-nested').exists()
        assert updated_nested_policy.reload().present_in_cinder is True

    def test_only_amo_labelled_policies_added(self):
        data = [
            {
                'uuid': uuid.uuid4().hex,
                'name': 'MoSo labeled',
                'description': 'SKIPPED',
                'labels': [{'name': 'MoSo'}],
                'nested_policies': [
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under MoSo, No label',
                        'description': 'SKIPPED',
                    },
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under MoSo, AMO labeled',
                        'description': 'SKIPPED',
                        'labels': [{'name': 'AMO'}],
                    },
                ],
            },
            {
                'uuid': uuid.uuid4().hex,
                'name': 'No label',
                'description': 'ADDED',
                'nested_policies': [
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under no label, no label',
                        'description': 'ADDED',
                    },
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under no label, MoSo labeled',
                        'description': 'SKIPPED',
                        'labels': [{'name': 'MoSo'}],
                    },
                ],
            },
            {
                'uuid': uuid.uuid4().hex,
                'name': 'AMO labeled',
                'description': 'ADDED',
                'labels': [{'name': 'AMO'}],
                'nested_policies': [
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under AMO label',
                        'description': 'ADDED',
                    },
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under AMO label, MoSo labeled',
                        'description': 'SKIPPED',
                        'labels': [{'name': 'MoSo'}],
                    },
                ],
            },
            {
                'uuid': uuid.uuid4().hex,
                'name': 'AMO & MoSo labeled',
                'description': 'ADDED',
                'labels': [{'name': 'AMO'}, {'name': 'MoSo'}],
                'nested_policies': [
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under two labels',
                        'description': 'ADDED',
                    },
                    {
                        'uuid': uuid.uuid4().hex,
                        'name': 'Nested under two label, MoSo labeled',
                        'description': 'SKIPPED',
                        'labels': [{'name': 'MoSo'}],
                    },
                ],
            },
        ]
        responses.add(responses.GET, self.url, json=data, status=200)

        sync_cinder_policies.delay()
        assert CinderPolicy.objects.count() == 6
        assert CinderPolicy.objects.filter(text='ADDED').count() == 6

    def test_enforcement_actions_synced(self):
        data = [
            {
                'uuid': 'no-actions',
                'name': 'no actions',
                'description': '',
                'enforcement_actions': [],
            },
            {
                'uuid': 'multiple',
                'name': 'multiple',
                'description': '',
                'enforcement_actions': [
                    {'slug': 'amo-disable-addon'},
                    {'slug': 'amo-approve'},
                    {'slug': 'amo-ban-user'},
                    {'slug': 'some-unsupported-action'},
                ],
            },
        ]

        responses.add(responses.GET, self.url, json=data, status=200)
        sync_cinder_policies.delay()
        assert CinderPolicy.objects.get(uuid='multiple').enforcement_actions == [
            'amo-disable-addon',
            'amo-approve',
            'amo-ban-user',
        ]
