from contextlib import contextmanager

from django.core.management import call_command
from django.core.management.base import CommandError

import mock
import pytest

from olympia import amo
from olympia.addons.management.commands import process_addons
from olympia.addons.models import Addon
from olympia.amo.tests import (
    TestCase, addon_factory, version_factory)
from olympia.files.models import FileValidation, WebextPermission
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

    with count_subtask_calls(process_addons.sign_addons) as calls:
        call_command('process_addons', task='sign_addons')
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids]

    with count_subtask_calls(process_addons.sign_addons) as calls:
        call_command('process_addons', task='sign_addons', limit=2)
        assert len(calls) == 1
        assert calls[0]['kwargs']['args'] == [addon_ids[:2]]


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
