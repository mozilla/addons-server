from contextlib import contextmanager

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.forms import ValidationError
from django.utils import translation

import mock
import pytest

from olympia import amo
from olympia.activity.models import AddonLog
from olympia.addons.management.commands import (
    approve_addons, process_addons as pa)
from olympia.addons.models import Addon
from olympia.amo.tests import (
    AMOPaths, TestCase, addon_factory, version_factory)
from olympia.applications.models import AppVersion
from olympia.files.models import FileValidation, WebextPermission
from olympia.reviewers.models import AutoApprovalSummary, ReviewerScore
from olympia.versions.models import ApplicationsVersions


# Where to monkeypatch "lib.crypto.tasks.sign_addons" so it's correctly mocked.
SIGN_ADDONS = 'olympia.addons.management.commands.sign_addons.sign_addons'


def test_sign_addons_force_signing(monkeypatch):
    """You can force signing an addon even if it's already signed."""
    def not_forced(ids, force, reason):
        assert not force
    monkeypatch.setattr(SIGN_ADDONS, not_forced)
    call_command('sign_addons', '123')

    def is_forced(ids, force, reason):
        assert force
    monkeypatch.setattr(SIGN_ADDONS, is_forced)
    call_command('sign_addons', '123', force=True)


def test_sign_addons_reason(monkeypatch):
    """You can pass a reason."""
    def has_reason(ids, force, reason):
        assert reason == 'expiry'
    monkeypatch.setattr(SIGN_ADDONS, has_reason)
    call_command('sign_addons', '123', reason='expiry')


def test_sign_addons_overwrite_autograph_settings(monkeypatch):
    def has_config_overwrite(ids, force, reason):
        config = settings.AUTOGRAPH_CONFIG
        assert config['server_url'] == 'dummy server url'
        assert config['user_id'] == 'dummy user id'
        assert config['key'] == 'dummy key'
        assert config['signer'] == 'dummy signer'

    monkeypatch.setattr(SIGN_ADDONS, has_config_overwrite)
    call_command(
        'sign_addons', '123',
        autograph_server_url='dummy server url',
        autograph_user_id='dummy user id',
        autograph_key='dummy key',
        autograph_signer='dummy signer')


@pytest.mark.django_db
def test_approve_addons_get_files_incomplete():
    """An incomplete add-on can't be approved."""
    addon = addon_factory(status=amo.STATUS_NULL)
    assert approve_addons.get_files([addon.guid]) == []


@pytest.mark.django_db
def test_approve_addons_get_files_bad_guid():
    """An add-on with another guid doesn't get approved."""
    addon1 = addon_factory(status=amo.STATUS_NOMINATED, guid='foo')
    addon1_file = addon1.find_latest_version(
        amo.RELEASE_CHANNEL_LISTED).files.get()
    addon1_file.update(status=amo.STATUS_AWAITING_REVIEW)
    # Create another add-on that we won't get the files for.
    addon2 = addon_factory(status=amo.STATUS_NOMINATED, guid='bar')
    addon2_file = addon2.find_latest_version(
        amo.RELEASE_CHANNEL_LISTED).files.get()
    addon2_file.update(status=amo.STATUS_AWAITING_REVIEW)
    # There's only the addon1's file returned, no other.
    assert approve_addons.get_files(['foo']) == [addon1_file]


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
            (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW, 'full')],
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


@pytest.fixture
def mozilla_user(db):
    """Create and return the "mozilla" user used to auto approve addons."""
    return amo.tests.user_factory(id=settings.TASK_USER_ID)


def test_approve_addons_get_files(use_case):
    """Files that need to get approved are returned in the list.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, file2, review_type = use_case
    assert approve_addons.get_files([addon.guid]) == [file1, file2]


@pytest.mark.django_db
def test_approve_addons_approve_files_no_review_type():
    """Files which don't need approval don't change status."""
    # Create the "mozilla" user, needed for the log.
    amo.tests.user_factory(id=settings.TASK_USER_ID)
    addon = addon_factory(status=amo.STATUS_PUBLIC)
    file_ = addon.versions.get().files.get()
    file_.update(status=amo.STATUS_PUBLIC)
    approve_addons.approve_files([(file_, None)])
    # Nothing changed.
    assert addon.reload().status == amo.STATUS_PUBLIC
    assert file_.reload().status == amo.STATUS_PUBLIC


def test_approve_addons_approve_files(use_case, mozilla_user):
    """Files are approved using the correct review type.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, file2, review_type = use_case
    approve_addons.approve_files([(file1, review_type),
                                  (file2, review_type)])
    assert file1.reload().status == amo.STATUS_PUBLIC
    assert file2.reload().status == amo.STATUS_PUBLIC
    logs = AddonLog.objects.filter(addon=addon)
    assert len(logs) == 2  # One per file.
    file1_log, file2_log = logs
    # An AddonLog has been created for each approval.
    assert file1_log.activity_log.details['comments'] == u'bulk approval'
    assert file1_log.activity_log.user == mozilla_user
    assert file2_log.activity_log.details['comments'] == u'bulk approval'
    assert file2_log.activity_log.user == mozilla_user
    # No ReviewerScore was granted, it's an automatic approval.
    assert not ReviewerScore.objects.all()


@pytest.mark.django_db
def test_approve_addons_get_review_type_already_approved():
    """The review type for a file that doesn't need approval is None."""
    addon = addon_factory(status=amo.STATUS_PUBLIC)
    file_ = addon.versions.get().files.get()
    file_.update(status=amo.STATUS_PUBLIC)
    assert approve_addons.get_review_type(file_) is None


def test_approve_addons_get_review_type(use_case):
    """Review type depends on the file and addon status.

    Use cases are quadruples taken from the "use_case" fixture above.
    """
    addon, file1, _, review_type = use_case
    assert approve_addons.get_review_type(file1) == review_type


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


@pytest.mark.django_db
def test_process_addons_limit_addons():
    addon_ids = [addon_factory().id for _ in range(5)]
    assert Addon.objects.count() == 5

    with count_subtask_calls(pa.sign_addons) as calls:
        call_command('process_addons', task='sign_addons')
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids]

    with count_subtask_calls(pa.sign_addons) as calls:
        call_command('process_addons', task='sign_addons', limit=2)
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids[:2]]

    with count_subtask_calls(pa.sign_addons) as calls:
        call_command('process_addons', task='sign_addons', limit='2')
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids[:2]]


class AddFirefox57TagTestCase(TestCase):
    def test_affects_only_public_webextensions(self):
        addon_factory()
        addon_factory(file_kw={'is_webextension': True,
                               'status': amo.STATUS_AWAITING_REVIEW},
                      status=amo.STATUS_NOMINATED)
        public_webextension = addon_factory(file_kw={'is_webextension': True})
        public_mozilla_signed = addon_factory(file_kw={
            'is_mozilla_signed_extension': True})

        with count_subtask_calls(pa.add_firefox57_tag) as calls:
            call_command(
                'process_addons', task='add_firefox57_tag_to_webextensions')

        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [
            [public_webextension.pk, public_mozilla_signed.pk]
        ]

    def test_tag_added_for_is_webextension(self):
        self.addon = addon_factory(file_kw={'is_webextension': True})
        assert self.addon.tags.all().count() == 0

        call_command(
            'process_addons', task='add_firefox57_tag_to_webextensions')

        assert (
            set(self.addon.tags.all().values_list('tag_text', flat=True)) ==
            set(['firefox57']))

    def test_tag_added_for_is_mozilla_signed_extension(self):
        self.addon = addon_factory(
            file_kw={'is_mozilla_signed_extension': True})
        assert self.addon.tags.all().count() == 0

        call_command(
            'process_addons', task='add_firefox57_tag_to_webextensions')

        assert (
            set(self.addon.tags.all().values_list('tag_text', flat=True)) ==
            set(['firefox57']))


class TestAddDynamicThemeTagForThemeApiCommand(TestCase):
    def test_affects_only_public_webextensions(self):
        addon_factory()
        addon_factory(file_kw={'is_webextension': True,
                               'status': amo.STATUS_AWAITING_REVIEW},
                      status=amo.STATUS_NOMINATED)
        public_webextension = addon_factory(file_kw={'is_webextension': True})

        with count_subtask_calls(pa.add_dynamic_theme_tag) as calls:
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
    def test_only_affects_auto_approved(self):
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

        with count_subtask_calls(pa.recalculate_post_review_weight) as calls:
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


class BumpAppVerForLegacyAddonsTestCase(AMOPaths, TestCase):
    def setUp(self):
        self.firefox_56_star, _ = AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='56.*')
        self.firefox_for_android_56_star, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='56.*')

    def test_only_affects_legacy_addons_targeting_firefox_lower_than_56(self):
        # Should be included:
        addon = addon_factory(version_kw={'max_app_version': '55.*'})
        addon2 = addon_factory(version_kw={'application': amo.ANDROID.id})
        addon3 = addon_factory(type=amo.ADDON_THEME)
        # Should not be included:
        addon_factory(file_kw={'is_webextension': True})
        addon_factory(version_kw={'max_app_version': '56.*'})

        with count_subtask_calls(pa.bump_appver_for_legacy_addons) as calls:
            call_command(
                'process_addons', task='bump_appver_for_legacy_addons')

        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [[addon.pk, addon2.pk, addon3.pk]]

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    @mock.patch('olympia.addons.tasks.bump_appver_for_addon_if_necessary')
    def test_reindex_if_updated_for_firefox_and_android(
            self, bump_appver_for_addon_if_necessary_mock, index_addons_mock):
        bump_appver_for_addon_if_necessary_mock.return_value = False
        # Note: technically this add-on is only compatible with Firefox, but
        # we're mocking the function that does the check anyway... we only care
        # about how the task behaves when bump_appver_for_legacy_addons()
        # returns False for both applications.
        addon = addon_factory()
        index_addons_mock.reset_mock()
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        assert bump_appver_for_addon_if_necessary_mock.call_count == 2

        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon.pk],)

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    @mock.patch('olympia.addons.tasks.bump_appver_for_addon_if_necessary')
    def test_reindex_if_updated_for_firefox(
            self, bump_appver_for_addon_if_necessary_mock, index_addons_mock):
        bump_appver_for_addon_if_necessary_mock.side_effect = (False, None)
        addon = addon_factory()
        index_addons_mock.reset_mock()
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        assert bump_appver_for_addon_if_necessary_mock.call_count == 2

        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon.pk],)

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    @mock.patch('olympia.addons.tasks.bump_appver_for_addon_if_necessary')
    def test_reindex_if_updated_for_android(
            self, bump_appver_for_addon_if_necessary_mock, index_addons_mock):
        bump_appver_for_addon_if_necessary_mock.side_effect = (None, False)
        addon = addon_factory()
        index_addons_mock.reset_mock()
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        assert bump_appver_for_addon_if_necessary_mock.call_count == 2

        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon.pk],)

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    @mock.patch('olympia.addons.tasks.bump_appver_for_addon_if_necessary')
    def test_no_update_necessary(
            self, bump_appver_for_addon_if_necessary_mock, index_addons_mock):
        bump_appver_for_addon_if_necessary_mock.return_value = True
        addon_factory()
        index_addons_mock.reset_mock()
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        assert bump_appver_for_addon_if_necessary_mock.call_count == 1
        # 0 index_addons calls since bump_appver_for_addon_if_necessary
        # returned True.
        assert index_addons_mock.call_count == 0

        index_addons_mock.reset_mock()
        bump_appver_for_addon_if_necessary_mock.reset_mock()
        bump_appver_for_addon_if_necessary_mock.return_value = None
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        # This time, since bump_appver_for_addon_if_necessary_mock returned
        # None the first time, we had to call a second time...
        assert bump_appver_for_addon_if_necessary_mock.call_count == 2
        # ... We still should have 0 add-ons to index.
        assert index_addons_mock.call_count == 0

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    @mock.patch('olympia.addons.tasks.storage.open')
    def test_exception_when_reading_xpi(
            self, open_mock, index_addons_mock):
        open_mock.side_effect = Exception
        # Add 2 add-ons for Firefox. We want to make sure both are considered
        # even though the open() calls are raising an exception (i.e. the
        # exception is caught and we go to the next add-on).
        addon_factory()
        addon_factory()
        index_addons_mock.reset_mock()
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        assert open_mock.call_count == 2

        # No index_addons call, but eh, we didn't raise an exception in the
        # middle of running the command/task.
        assert index_addons_mock.call_count == 0

    def test_correctly_updated(self):
        # This is a full test without mocks, so the file needs to exist.
        addon = addon_factory(version_kw={
            # Might as well match the xpi contents.
            'min_app_version': '3.0',
            'max_app_version': '3.6.*'
        })
        apv = ApplicationsVersions.objects.get(version=addon.current_version)
        assert apv.max != self.firefox_56_star
        self.xpi_copy_over(addon.current_version.all_files[0], 'extension.xpi')
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        apv = ApplicationsVersions.objects.get(version=addon.current_version)
        assert apv.max == self.firefox_56_star

    def test_correctly_ignored_because_strict_compatibility_is_enabled(self):
        # This is a full test without mocks, so the file needs to exist.
        addon = addon_factory(version_kw={
            # Might as well match the xpi contents.
            'min_app_version': '3.0',
            'max_app_version': '3.6.*'
        })
        apv = ApplicationsVersions.objects.get(version=addon.current_version)
        assert apv.max != self.firefox_56_star
        self.xpi_copy_over(
            addon.current_version.all_files[0], 'strict-compat.xpi')
        call_command('process_addons', task='bump_appver_for_legacy_addons')
        apv = ApplicationsVersions.objects.get(version=addon.current_version)
        # Shouldn't have been updated to 56.* since strictCompatibilty is true.
        assert apv.max != self.firefox_56_star


class TestMigrateLegacyDictionariesToWebextension(TestCase):
    @mock.patch('olympia.addons.tasks.index_addons.delay', autospec=True)
    @mock.patch(
        'olympia.addons.tasks.migrate_legacy_dictionary_to_webextension',
        autospec=True)
    def test_basic(self, migrate_legacy_dictionarymock, index_addons_mock):
        self.counter = 0

        def side_effect(*args, **kwargs):
            self.counter += 1
            if self.counter == 2:
                raise ValidationError('Dummy validation error')

        addon_factory()
        addon_factory(type=amo.ADDON_LPAPP)
        addon_factory(type=amo.ADDON_STATICTHEME)
        addon_factory(type=amo.ADDON_DICT, file_kw={'is_webextension': True})
        addon_factory(
            type=amo.ADDON_DICT, target_locale='es',
            status=amo.STATUS_DISABLED)
        addon_factory(
            type=amo.ADDON_DICT, target_locale='it',
            disabled_by_user=True)
        self.addon = addon_factory(type=amo.ADDON_DICT, target_locale='fr')
        self.addon2 = addon_factory(type=amo.ADDON_DICT, target_locale=None)
        self.addon3 = addon_factory(type=amo.ADDON_DICT, target_locale='')
        migrate_legacy_dictionarymock.side_effect = side_effect
        index_addons_mock.reset_mock()

        call_command('process_addons',
                     task='migrate_legacy_dictionaries_to_webextension')
        assert migrate_legacy_dictionarymock.call_count == 3
        actual_calls = (
            migrate_legacy_dictionarymock.call_args_list[0][0][0],
            migrate_legacy_dictionarymock.call_args_list[1][0][0],
            migrate_legacy_dictionarymock.call_args_list[2][0][0]
        )
        expected_calls = (self.addon, self.addon2, self.addon3)
        assert actual_calls == expected_calls
        # self.addon2 will raise a ValidationError because of the side_effect
        # above, so we should only reindex 1 and 3.
        assert index_addons_mock.call_args[0][0] == [self.addon, self.addon3]


class TestExtractWebextensionsToGitStorage(TestCase):
    @mock.patch('olympia.addons.tasks.index_addons.delay', autospec=True)
    @mock.patch(
        'olympia.addons.tasks.extract_file_obj_to_git', autospec=True)
    def test_basic(self, extract_file_obj_to_git_mock, index_addons_mock):
        addon_factory(file_kw={'is_webextension': True})
        addon_factory(file_kw={'is_webextension': True})
        addon_factory(
            type=amo.ADDON_STATICTHEME, file_kw={'is_webextension': True})
        addon_factory(
            file_kw={'is_webextension': True}, status=amo.STATUS_DISABLED)
        addon_factory(type=amo.ADDON_LPAPP, file_kw={'is_webextension': True})
        addon_factory(type=amo.ADDON_DICT, file_kw={'is_webextension': True})

        # Not supported, we focus entirely on WebExtensions
        addon_factory(type=amo.ADDON_THEME)
        addon_factory()
        addon_factory()
        addon_factory(type=amo.ADDON_LPAPP, file_kw={'is_webextension': False})
        addon_factory(type=amo.ADDON_DICT, file_kw={'is_webextension': False})

        call_command('process_addons',
                     task='extract_webextensions_to_git_storage')
        assert extract_file_obj_to_git_mock.call_count == 6


class TestDisableLegacyAddons(TestCase):
    def test_basic(self):
        # These add-ons should be disabled completely since they only have a
        # single legacy file.
        should_be_fully_disabled = [
            addon_factory(),
            addon_factory(type=amo.ADDON_LPAPP),
            addon_factory(type=amo.ADDON_THEME),
        ]

        # This one has a legacy and a non-legacy version, so only the legacy
        # File & Version should be disabled.
        should_have_old_version_disabled = [
            addon_factory(created=self.days_ago(42),
                          version_kw={'created': self.days_ago(42)}),
        ]
        version_factory(
            addon=should_have_old_version_disabled[0],
            file_kw={'is_webextension': True})

        # These should *not* have any File instance disabled, they should be
        # kept intact.
        should_be_kept_intact = [
            addon_factory(file_kw={'is_webextension': True}),
            addon_factory(file_kw={'is_mozilla_signed_extension': True}),
            addon_factory(file_kw={'is_mozilla_signed_extension': True,
                                   'is_webextension': True}),
            addon_factory(type=amo.ADDON_DICT),
            addon_factory(type=amo.ADDON_SEARCH),
        ]

        call_command('process_addons', task='disable_legacy_files')

        for addon in should_be_fully_disabled:
            addon.reload()
            assert addon.status == amo.STATUS_NULL  # No public version left.
            assert addon.current_version is None
            file_ = addon.versions.all()[0].files.all()[0]
            assert file_.status == amo.STATUS_DISABLED

        for addon in should_have_old_version_disabled:
            addon.reload()
            assert addon.status == amo.STATUS_PUBLIC
            assert addon.current_version
            file_ = addon.current_version.files.all()[0]
            assert file_.status == amo.STATUS_PUBLIC
            file_ = addon.versions.exclude(
                pk=addon.current_version.pk)[0].files.all()[0]
            assert file_.status == amo.STATUS_DISABLED

        for addon in should_be_kept_intact:
            addon.reload()
            assert addon.status == amo.STATUS_PUBLIC
            assert addon.current_version
            file_ = addon.versions.all()[0].all_files[0]
            assert file_.status == amo.STATUS_PUBLIC


class TestRemoveAMOLinksInURLFields(TestCase):
    domain = settings.DOMAIN
    allowed_url = u'https://example.org'

    def test_remove_links_in_homepages(self):
        addons = [
            addon_factory(homepage=u'%s' % self.domain),
            addon_factory(homepage=u'https://%s/page.html' % self.domain),
        ]

        call_command('process_addons', task='remove_amo_links_in_url_fields')

        for addon in addons:
            addon.reload()
            assert addon.homepage.localized_string == u''
            assert addon.homepage.localized_string_clean == u''

    def test_remove_links_in_support_urls(self):
        addons = [
            addon_factory(support_url=u'%s' % self.domain),
            addon_factory(support_url=u'https://%s/page.html' % self.domain),
        ]

        call_command('process_addons', task='remove_amo_links_in_url_fields')

        for addon in addons:
            addon.reload()
            assert addon.support_url.localized_string == u''
            assert addon.support_url.localized_string_clean == u''

    def test_remove_links_in_contributions(self):
        addons = [
            addon_factory(contributions=u'%s' % self.domain),
            addon_factory(contributions=u'https://%s/page.html' % self.domain),
        ]

        call_command('process_addons', task='remove_amo_links_in_url_fields')

        for addon in addons:
            addon.reload()
            assert addon.contributions == u''

    def test_remove_links_in_support_url_and_homepage(self):
        addons = [
            addon_factory(
                homepage=u'http://%s' % self.domain,
                support_url=u'%s' % self.domain,
            ),
        ]
        should_be_kept_intact = [
            addon_factory(support_url=self.allowed_url),
        ]

        call_command('process_addons', task='remove_amo_links_in_url_fields')

        for addon in addons:
            addon.reload()
            assert addon.homepage == u''
            assert addon.support_url == u''
        for addon in should_be_kept_intact:
            addon.reload()
            assert addon.support_url == self.allowed_url

    def test_with_multiple_translations(self):
        addon = addon_factory(support_url={
            'en-US': self.allowed_url,
            'fr': u'http://%s' % self.domain,
        })

        call_command('process_addons', task='remove_amo_links_in_url_fields')

        translation.activate('en-US')
        addon.reload()
        assert addon.support_url == self.allowed_url

        translation.activate('fr')
        addon.reload()
        assert addon.support_url == u''
