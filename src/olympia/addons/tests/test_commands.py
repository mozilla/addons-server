import random
from contextlib import contextmanager
from datetime import datetime, timedelta

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test.utils import override_settings

from freezegun import freeze_time
from unittest import mock
import pytest

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.management.commands import process_addons
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, MigratedLWT, ReusedGUID, GUID_REUSE_FORMAT)
from olympia.abuse.models import AbuseReport
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.files.models import FileValidation, WebextPermission
from olympia.ratings.models import Rating
from olympia.reviewers.models import AutoApprovalSummary
from olympia.versions.models import VersionPreview


def id_function(fixture_value):
    """Convert a param from the use_case fixture to a nicer name.

    By default, the name (used in the test generated from the parameterized
    fixture) will use the fixture name and a number.
    Eg: test_foo[use_case0]

    Providing explicit 'ids' (either as strings, or as a function) will use
    those names instead. Here the name will be something like
    test_foo[public-unreviewed-full], for the status values, and if the file is
    unreviewed.
    """
    addon_status, file_status, review_type = fixture_value
    return '{0}-{1}-{2}'.format(amo.STATUS_CHOICES_API[addon_status],
                                amo.STATUS_CHOICES_API[file_status],
                                review_type)


@pytest.fixture(
    params=[(amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, 'full'),
            (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW, 'full')],
    # ids are used to build better names for the tests using this fixture.
    ids=id_function)
def use_case(request, db):
    """This fixture will return quadruples for different use cases.

    Addon                   | File1 and 2        | Review type
    ==============================================================
    awaiting review         | awaiting review    | approved
    approved                | awaiting review    | approved
    """
    addon_status, file_status, review_type = request.param

    addon = addon_factory(status=addon_status, guid='foo')
    version = addon.find_latest_version(amo.RELEASE_CHANNEL_LISTED)
    file1 = version.files.get()
    file1.update(status=file_status)
    # A second file for good measure.
    file2 = amo.tests.file_factory(version=version, status=file_status)
    # If the addon is public, and we change its only file to something else
    # than public, it'll change to unreviewed.
    addon.update(status=addon_status)
    assert addon.reload().status == addon_status
    assert file1.reload().status == file_status
    assert file2.reload().status == file_status

    return (addon, file1, file2, review_type)


def test_process_addons_invalid_task():
    with pytest.raises(CommandError):
        call_command('process_addons', task='foo')


@contextmanager
def count_subtask_calls(original_function):
    """Mock a celery tasks subtask method and record it's calls.

    You can't mock a celery task `.subtask` method if that task is used
    inside a chord or group unfortunately because of some type checking
    that is use inside Celery 4+.

    So this wraps the original method and restores it and records the calls
    on it's own.
    """
    original_function_subtask = original_function.subtask
    called = []

    def _subtask_wrapper(*args, **kwargs):
        called.append({'args': args, 'kwargs': kwargs})
        return original_function_subtask(*args, **kwargs)

    original_function.subtask = _subtask_wrapper

    yield called

    original_function.subtask = original_function_subtask


@freeze_time('2019-04-01')
@pytest.mark.django_db
def test_process_addons_limit_addons():
    addon_ids = [
        addon_factory(status=amo.STATUS_APPROVED).id for _ in range(5)
    ]
    assert Addon.objects.count() == 5

    with count_subtask_calls(process_addons.sign_addons) as calls:
        call_command('process_addons', task='resign_addons_for_cose')
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids]

    with count_subtask_calls(process_addons.sign_addons) as calls:
        call_command('process_addons', task='resign_addons_for_cose', limit=2)
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids[:2]]


@pytest.mark.django_db
@mock.patch.object(process_addons.Command, 'get_pks')
def test_process_addons_batch_size(mock_get_pks):
    addon_ids = [
        random.randrange(1000) for _ in range(101)
    ]
    mock_get_pks.return_value = addon_ids

    with count_subtask_calls(process_addons.recreate_previews) as calls:
        call_command('process_addons', task='recreate_previews')
        assert len(calls) == 2
        assert calls[0]['kwargs']['args'] == [addon_ids[:100]]
        assert calls[1]['kwargs']['args'] == [addon_ids[100:]]

    with count_subtask_calls(process_addons.recreate_previews) as calls:
        call_command(
            'process_addons', task='recreate_previews',
            **{'batch_size': 50})
        assert len(calls) == 3
        assert calls[0]['kwargs']['args'] == [addon_ids[:50]]
        assert calls[1]['kwargs']['args'] == [addon_ids[50:100]]
        assert calls[2]['kwargs']['args'] == [addon_ids[100:]]


class TestAddDynamicThemeTagForThemeApiCommand(TestCase):
    def test_affects_only_public_webextensions(self):
        addon_factory()
        addon_factory(file_kw={'is_webextension': True,
                               'status': amo.STATUS_AWAITING_REVIEW},
                      status=amo.STATUS_NOMINATED)
        public_webextension = addon_factory(file_kw={'is_webextension': True})

        with count_subtask_calls(
                process_addons.add_dynamic_theme_tag) as calls:
            call_command(
                'process_addons', task='add_dynamic_theme_tag_for_theme_api')

        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [
            [public_webextension.pk]
        ]

    def test_tag_added_for_is_dynamic_theme(self):
        addon = addon_factory(file_kw={'is_webextension': True})
        WebextPermission.objects.create(
            file=addon.current_version.all_files[0],
            permissions=['theme'])
        assert addon.tags.all().count() == 0
        # Add some more that shouldn't be tagged
        no_perms = addon_factory(file_kw={'is_webextension': True})
        not_a_theme = addon_factory(file_kw={'is_webextension': True})
        WebextPermission.objects.create(
            file=not_a_theme.current_version.all_files[0],
            permissions=['downloads'])

        call_command(
            'process_addons', task='add_dynamic_theme_tag_for_theme_api')

        assert (
            list(addon.tags.all().values_list('tag_text', flat=True)) ==
            [u'dynamic theme'])

        assert not no_perms.tags.all().exists()
        assert not not_a_theme.tags.all().exists()


class RecalculateWeightTestCase(TestCase):
    def test_only_affects_auto_approved_and_unconfirmed(self):
        # Non auto-approved add-on, should not be considered.
        addon_factory()

        # Non auto-approved add-on that has an AutoApprovalSummary entry,
        # should not be considered.
        AutoApprovalSummary.objects.create(
            version=addon_factory().current_version,
            verdict=amo.NOT_AUTO_APPROVED)

        # Add-on with the current version not auto-approved, should not be
        # considered.
        extra_addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=extra_addon.current_version, verdict=amo.AUTO_APPROVED)
        extra_addon.current_version.update(created=self.days_ago(1))
        version_factory(addon=extra_addon)

        # Add-on that was auto-approved but already confirmed, should not be
        # considered, it's too late.
        already_confirmed_addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=already_confirmed_addon.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)

        # Add-on that should be considered because it's current version is
        # auto-approved.
        auto_approved_addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=auto_approved_addon.current_version,
            verdict=amo.AUTO_APPROVED)
        # Add some extra versions that should not have an impact.
        version_factory(
            addon=auto_approved_addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=auto_approved_addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        with count_subtask_calls(
                process_addons.recalculate_post_review_weight) as calls:
            call_command(
                'process_addons', task='recalculate_post_review_weight')

        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [[auto_approved_addon.pk]]

    def test_task_works_correctly(self):
        addon = addon_factory(average_daily_users=100000)
        FileValidation.objects.create(
            file=addon.current_version.all_files[0], validation=u'{}')
        addon = Addon.objects.get(pk=addon.pk)
        summary = AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        assert summary.weight == 0

        call_command(
            'process_addons', task='recalculate_post_review_weight')

        summary.reload()
        # Weight should be 10 because of average_daily_users / 10000.
        assert summary.weight == 10


class ConstantlyRecalculateWeightTestCase(TestCase):
    def test_affects_correct_addons(self):
        # *not considered* - Non auto-approved add-on
        addon_factory()

        # *not considered* - Non auto-approved add-on that has an
        # AutoApprovalSummary entry
        AutoApprovalSummary.objects.create(
            version=addon_factory().current_version,
            verdict=amo.NOT_AUTO_APPROVED)

        # *not considered* -Add-on with the current version not auto-approved
        extra_addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=extra_addon.current_version, verdict=amo.AUTO_APPROVED)
        extra_addon.current_version.update(created=self.days_ago(1))
        version_factory(addon=extra_addon)

        # *not considered* - current version is auto-approved but doesn't
        # have recent abuse reports or low ratings
        auto_approved_addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=auto_approved_addon.current_version,
            verdict=amo.AUTO_APPROVED)

        # *considered* - current version is auto-approved and
        # has a recent rating with rating <= 3
        auto_approved_addon1 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon1.current_version,
            verdict=amo.AUTO_APPROVED)
        Rating.objects.create(
            created=summary.modified + timedelta(days=3),
            addon=auto_approved_addon1,
            version=auto_approved_addon1.current_version,
            rating=2, body='Apocalypse', user=user_factory()),

        # *not considered* - current version is auto-approved but
        # has a recent rating with rating > 3
        auto_approved_addon2 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon2.current_version,
            verdict=amo.AUTO_APPROVED)
        Rating.objects.create(
            created=summary.modified + timedelta(days=3),
            addon=auto_approved_addon2,
            version=auto_approved_addon2.current_version,
            rating=4, body='Apocalypse', user=user_factory()),

        # *not considered* - current version is auto-approved but
        # has a recent rating with rating > 3
        auto_approved_addon3 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon3.current_version,
            verdict=amo.AUTO_APPROVED)
        Rating.objects.create(
            created=summary.modified + timedelta(days=3),
            addon=auto_approved_addon3,
            version=auto_approved_addon3.current_version,
            rating=4, body='Apocalypse', user=user_factory()),

        # *not considered* - current version is auto-approved but
        # has a low rating that isn't recent enough
        auto_approved_addon4 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon4.current_version,
            verdict=amo.AUTO_APPROVED)
        Rating.objects.create(
            created=summary.modified - timedelta(days=3),
            addon=auto_approved_addon4,
            version=auto_approved_addon4.current_version,
            rating=1, body='Apocalypse', user=user_factory()),

        # *considered* - current version is auto-approved and
        # has a recent abuse report
        auto_approved_addon5 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon5.current_version,
            verdict=amo.AUTO_APPROVED)
        AbuseReport.objects.create(
            addon=auto_approved_addon5,
            created=summary.modified + timedelta(days=3))

        # *not considered* - current version is auto-approved but
        # has an abuse report that isn't recent enough
        auto_approved_addon6 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon6.current_version,
            verdict=amo.AUTO_APPROVED)
        AbuseReport.objects.create(
            addon=auto_approved_addon6,
            created=summary.modified - timedelta(days=3))

        # *considered* - current version is auto-approved and
        # has an abuse report through it's author that is recent enough
        author = user_factory()
        auto_approved_addon7 = addon_factory(users=[author])
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon7.current_version,
            verdict=amo.AUTO_APPROVED)
        AbuseReport.objects.create(
            user=author,
            created=summary.modified + timedelta(days=3))

        # *not considered* - current version is auto-approved and
        # has an abuse report through it's author that is recent enough
        # BUT the abuse report is deleted.
        author = user_factory()
        auto_approved_addon8 = addon_factory(users=[author])
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon8.current_version,
            verdict=amo.AUTO_APPROVED)
        AbuseReport.objects.create(
            user=author,
            state=AbuseReport.STATES.DELETED,
            created=summary.modified + timedelta(days=3))

        # *not considered* - current version is auto-approved and
        # has a recent rating with rating <= 3
        # but the rating is deleted.
        auto_approved_addon9 = addon_factory()
        summary = AutoApprovalSummary.objects.create(
            version=auto_approved_addon9.current_version,
            verdict=amo.AUTO_APPROVED)
        Rating.objects.create(
            created=summary.modified + timedelta(days=3),
            addon=auto_approved_addon9,
            version=auto_approved_addon9.current_version,
            deleted=True,
            rating=2, body='Apocalypse', user=user_factory()),

        # *considered* - current version is auto-approved and
        # has an abuse report through it's author that is recent enough
        # Used to test that we only recalculate the weight for
        # the most recent version
        author = user_factory()
        auto_approved_addon8 = addon_factory(
            users=[author], version_kw={'version': '0.1'})

        AutoApprovalSummary.objects.create(
            version=auto_approved_addon8.current_version,
            verdict=amo.AUTO_APPROVED)

        # Let's create a new `current_version` and summary
        current_version = version_factory(
            addon=auto_approved_addon8, version='0.2')

        summary = AutoApprovalSummary.objects.create(
            version=current_version,
            verdict=amo.AUTO_APPROVED)

        AbuseReport.objects.create(
            user=author,
            created=summary.modified + timedelta(days=3))

        mod = 'olympia.reviewers.tasks.AutoApprovalSummary.calculate_weight'
        with mock.patch(mod) as calc_weight_mock:
            with count_subtask_calls(
                    process_addons.recalculate_post_review_weight) as calls:
                call_command(
                    'process_addons',
                    task='constantly_recalculate_post_review_weight')

        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [[
            auto_approved_addon1.pk,
            auto_approved_addon5.pk,
            auto_approved_addon7.pk,
            auto_approved_addon8.pk,
        ]]

        # Only 4 calls for each add-on, doesn't consider the extra version
        # that got created for addon 8
        assert calc_weight_mock.call_count == 4


class TestExtractWebextensionsToGitStorage(TestCase):
    @mock.patch('olympia.addons.tasks.index_addons.delay', autospec=True)
    @mock.patch(
        'olympia.versions.tasks.extract_version_to_git', autospec=True)
    def test_basic(self, extract_version_to_git_mock, index_addons_mock):
        addon_factory(file_kw={'is_webextension': True})
        addon_factory(file_kw={'is_webextension': True})
        addon_factory(
            type=amo.ADDON_STATICTHEME, file_kw={'is_webextension': True})
        addon_factory(
            file_kw={'is_webextension': True}, status=amo.STATUS_DISABLED)
        addon_factory(type=amo.ADDON_LPAPP, file_kw={'is_webextension': True})
        addon_factory(type=amo.ADDON_DICT, file_kw={'is_webextension': True})
        addon_factory(
            type=amo.ADDON_SEARCH, file_kw={'is_webextension': False})

        # Not supported, we focus entirely on WebExtensions
        # (except for search plugins)
        addon_factory(type=amo.ADDON_THEME)
        addon_factory()
        addon_factory()
        addon_factory(type=amo.ADDON_LPAPP, file_kw={'is_webextension': False})
        addon_factory(type=amo.ADDON_DICT, file_kw={'is_webextension': False})

        call_command('process_addons',
                     task='extract_webextensions_to_git_storage')

        assert extract_version_to_git_mock.call_count == 7


class TestExtractColorsFromStaticThemes(TestCase):
    @mock.patch('olympia.addons.tasks.extract_colors_from_image')
    def test_basic(self, extract_colors_from_image_mock):
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        preview = VersionPreview.objects.create(version=addon.current_version)
        extract_colors_from_image_mock.return_value = [
            {'h': 4, 's': 8, 'l': 15, 'ratio': .16}
        ]
        call_command(
            'process_addons', task='extract_colors_from_static_themes')
        preview.reload()
        assert preview.colors == [
            {'h': 4, 's': 8, 'l': 15, 'ratio': .16}
        ]


class TestDeleteArmagaddonRatings(TestCase):
    @mock.patch('olympia.ratings.tasks.index_addons')
    def test_basic(self, index_addons_mock):
        self.addon1 = addon_factory()
        self.addon2 = addon_factory()
        self.addon3 = addon_factory()

        # Ratings made during Armagadd-on.
        delete_me = [
            Rating.objects.create(
                created=datetime(2019, 5, 6, 7, 42), addon=self.addon1,
                rating=1, body='Apocalypse', user=user_factory()),
            Rating.objects.create(
                created=datetime(2019, 5, 3, 22, 14), addon=self.addon1,
                rating=2, body='ἀποκάλυψις', user=user_factory()),
            Rating.objects.create(
                created=datetime(2019, 5, 4, 0, 0), addon=self.addon2,
                rating=3, user=user_factory()),
        ]

        # Ratings made during, but that should be kept because of their score,
        # or made before and after.
        keep_me = [
            Rating.objects.create(
                created=datetime(2019, 5, 5, 0, 0), addon=self.addon1,
                rating=4, body='High Score!', user=user_factory()),
            Rating.objects.create(
                created=datetime(2019, 4, 1, 0, 0), addon=self.addon2,
                rating=1, body='Before', user=user_factory()),
            Rating.objects.create(
                created=datetime(2019, 6, 1, 0, 0), addon=self.addon3,
                rating=2, body='After', user=user_factory()),
        ]

        self.addon1.reload()
        assert self.addon1.average_rating == 2.3333
        self.addon2.reload()
        assert self.addon2.average_rating == 2.0

        # Create a dummy task user and launch the command.
        fake_task_user = user_factory()
        with override_settings(TASK_USER_ID=fake_task_user.pk):
            call_command(
                'process_addons', task='delete_armagaddon_ratings_for_addons')

        # We should have soft-deleted 3 ratings, leaving 3 untouched.
        assert Rating.unfiltered.count() == 6
        assert Rating.objects.count() == 3

        for rating in keep_me:
            rating.reload()
            assert not rating.deleted

        for rating in delete_me:
            rating.reload()
            assert rating.deleted

        # We should have added activity logs for the deletion.
        assert ActivityLog.objects.filter(
            action=amo.LOG.DELETE_RATING.id, user=fake_task_user).count() == 3

        # We shouldn't have sent any mails about it.
        assert len(mail.outbox) == 0

        # We should have fixed the average ratings for affected add-ons.
        self.addon1.reload()
        assert self.addon1.average_rating == 4.0
        self.addon2.reload()
        assert self.addon2.average_rating == 1.0

        # We should have reindexed only the 2 add-ons that had ratings we
        # deleted.
        assert index_addons_mock.delay.call_count == 1
        index_addons_mock.delay.call_args == [self.addon1.pk, self.addon2.pk]


class TestResignAddonsForCose(TestCase):
    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_basic(self, sign_file_mock):
        file_kw = {'is_webextension': True, 'filename': 'webextension.xpi'}

        with freeze_time('2019-04-01'):
            addon_with_history = addon_factory(file_kw=file_kw)
            # Create a few more versions for this add-on to test that we only
            # re-sign current versions
            version_factory(addon=addon_with_history, file_kw=file_kw)
            version_factory(addon=addon_with_history, file_kw=file_kw)
            version_factory(addon=addon_with_history, file_kw=file_kw)

            addon_factory(file_kw=file_kw)
            addon_factory(type=amo.ADDON_STATICTHEME, file_kw=file_kw)
            addon_factory(type=amo.ADDON_LPAPP, file_kw=file_kw)
            addon_factory(type=amo.ADDON_DICT, file_kw=file_kw)

        # Don't resign add-ons created after April 4th 2019
        with freeze_time('2019-05-01'):
            addon_factory(file_kw=file_kw)
            addon_factory(type=amo.ADDON_STATICTHEME, file_kw=file_kw)

        # Search add-ons won't get re-signed, same with deleted and disabled
        # versions. Also, only public addons are being resigned
        addon_factory(type=amo.ADDON_SEARCH, file_kw=file_kw)
        addon_factory(status=amo.STATUS_DISABLED, file_kw=file_kw)
        addon_factory(status=amo.STATUS_AWAITING_REVIEW, file_kw=file_kw)
        addon_factory(status=amo.STATUS_NULL, file_kw=file_kw)

        call_command('process_addons', task='resign_addons_for_cose')

        assert sign_file_mock.call_count == 5


class TestContentApproveMigratedThemes(TestCase):
    def test_basic(self):
        # Pretend those 3 static themes were migrated. Only the first one
        # should be marked as content approved by the command.
        static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        static_theme_already_content_approved = addon_factory(
            type=amo.ADDON_STATICTHEME)
        static_theme_not_public = addon_factory(
            type=amo.ADDON_STATICTHEME, status=amo.STATUS_NOMINATED)
        AddonApprovalsCounter.approve_content_for_addon(
            static_theme_already_content_approved)
        migrated_themes = [
            static_theme,
            static_theme_already_content_approved,
            static_theme_not_public
        ]
        migration_date = self.days_ago(123)
        for addon in migrated_themes:
            MigratedLWT.objects.create(
                static_theme=addon,
                lightweight_theme_id=9999,
                getpersonas_id=0,
                created=migration_date)
        # Add another that never went through migration, it was born that way.
        non_migrated_theme = addon_factory(type=amo.ADDON_STATICTHEME)

        call_command('process_addons', task='content_approve_migrated_themes')

        approvals_info = AddonApprovalsCounter.objects.get(addon=static_theme)
        assert approvals_info.last_content_review == migration_date

        approvals_info = AddonApprovalsCounter.objects.get(
            addon=static_theme_already_content_approved)
        assert approvals_info.last_content_review != migration_date
        self.assertCloseToNow(approvals_info.last_content_review)

        assert not AddonApprovalsCounter.objects.filter(
            addon=non_migrated_theme).exists()

        assert not AddonApprovalsCounter.objects.filter(
            addon=static_theme_not_public).exists()


@pytest.mark.django_db
def test_backfill_reused_guid():
    # shouldn't show up in the query but throw them in anyway
    addon_factory(name='just a deleted addon', status=amo.STATUS_DELETED)
    addon_factory(name='just a public addon')
    # simple case - an add-on's guid is reused once.
    single_reuse_deleted = addon_factory(
        name='single reuse', status=amo.STATUS_DELETED)
    single_reuse_addon = addon_factory(
        name='single reuse', guid='single@reuse')
    single_reuse_deleted.update(
        guid=GUID_REUSE_FORMAT.format(single_reuse_addon.id))
    # more complex case - a guid is reused multiple times.
    multi_reuse_deleted_a = addon_factory(
        name='multi reuse', status=amo.STATUS_DELETED)
    multi_reuse_deleted_b = addon_factory(
        name='multi reuse', status=amo.STATUS_DELETED)
    multi_reuse_addon = addon_factory(
        name='multi reuse', guid='multi@reuse')
    multi_reuse_deleted_a.update(
        guid=GUID_REUSE_FORMAT.format(multi_reuse_deleted_b.id))
    multi_reuse_deleted_b.update(
        guid=GUID_REUSE_FORMAT.format(multi_reuse_addon.id))
    # a guid reuse referencing a pk that doesn't exist (addon hard delete?)
    addon_factory(
        name='missing reuse', status=amo.STATUS_DELETED,
        guid=GUID_REUSE_FORMAT.format(999))
    # reusedguid object already there
    reused_exists_deleted = addon_factory(
        name='reused_exists', status=amo.STATUS_DELETED)
    reused_exists_addon = addon_factory(
        name='reused_exists', guid='exists@reuse')
    reused_exists_deleted.update(
        guid=GUID_REUSE_FORMAT.format(reused_exists_addon.id))
    ReusedGUID.objects.create(addon=reused_exists_deleted, guid='exists@reuse')

    assert ReusedGUID.objects.count() == 1
    call_command('backfill_reused_guid')
    assert ReusedGUID.objects.count() == 4
    qs_values = ReusedGUID.objects.all().order_by('id').values('addon', 'guid')
    assert list(qs_values) == [
        {'addon': reused_exists_deleted.id, 'guid': 'exists@reuse'},
        {'addon': single_reuse_deleted.id, 'guid': 'single@reuse'},
        {'addon': multi_reuse_deleted_a.id, 'guid': 'multi@reuse'},
        {'addon': multi_reuse_deleted_b.id, 'guid': 'multi@reuse'},
    ]


class TestDeleteObsoleteAddons(TestCase):
    def setUp(self):
        # Some add-ons that shouldn't be deleted
        self.extension = addon_factory()
        self.static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        self.dictionary = addon_factory(type=amo.ADDON_DICT)
        # And some obsolete ones
        addon_factory(type=amo.ADDON_THEME)
        addon_factory().update(type=amo.ADDON_LPADDON)
        addon_factory().update(type=amo.ADDON_PLUGIN)
        addon_factory(type=9)  # _ADDON_PERSONA
        addon_factory().update(type=11)  # webapp

        assert Addon.unfiltered.count() == 8

    def test_hard(self):
        call_command(
            'process_addons', task='delete_obsolete_addons', with_deleted=True)

        assert Addon.unfiltered.count() == 3
        assert Addon.unfiltered.get(id=self.extension.id)
        assert Addon.unfiltered.get(id=self.static_theme.id)
        assert Addon.unfiltered.get(id=self.dictionary.id)

    def test_hard_with_already_deleted(self):
        Addon.unfiltered.update(status=amo.STATUS_DELETED)
        self.test_hard()

    def test_normal(self):
        call_command(
            'process_addons', task='delete_obsolete_addons')

        assert Addon.unfiltered.count() == 8
        assert Addon.objects.count() == 3
        assert Addon.objects.get(id=self.extension.id)
        assert Addon.objects.get(id=self.static_theme.id)
        assert Addon.objects.get(id=self.dictionary.id)
