import csv
import os
import tempfile
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.applications.models import AppVersion
from olympia.blocklist.models import Block, BlockType, BlockVersion
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.versions.compare import version_int
from olympia.versions.management.commands.force_min_android_compatibility import (
    Command as ForceMinAndroidCompatibility,
)
from olympia.versions.models import ApplicationsVersions, Version


class TestForceMinAndroidCompatibility(TestCase):
    def setUp(self):
        self.min_version_fenix = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )[0]
        self.max_version_fennec = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
        )[0]

    def _create_csv(self, contents):
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False
        ) as csv_file:
            self.addCleanup(os.remove, csv_file.name)
            writer = csv.writer(csv_file)
            writer.writerows(contents)
        return csv_file.name

    def test_missing_csv_path(self):
        with self.assertRaises(CommandError):
            call_command('force_min_android_compatibility')

    def test_init_csv_parsing(self):
        file_working_name = self._create_csv(
            [['addon_id'], ['123456789'], ['4815162342'], ['007'], ['42'], [' 57 ']]
        )
        command = ForceMinAndroidCompatibility()
        assert command.read_csv(file_working_name) == [123456789, 4815162342, 7, 42, 57]

    def test_full(self):
        addons_to_modify = [
            addon_factory(name='Not yet compatible with Android'),
            addon_factory(
                name='Already compatible with Android with strict_compatibility',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '68.*',
                },
                file_kw={'strict_compatibility': True},
            ),
            addon_factory(
                name='Already compatible with Android',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '120.0',
                    'max_app_version': '*',
                },
            ),
        ]
        addons_to_ignore_promoted = [
            addon_factory(
                name='Recommended for Android',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
                promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            ),
            addon_factory(
                name='Line for all',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
                promoted_id=PROMOTED_GROUP_CHOICES.LINE,
            ),
        ]
        addons_to_ignore_not_in_csv = [addon_factory(name='Not in csv')]
        csv_path = self._create_csv(
            [
                ['addon_id'],
                *[[str(addon.pk)] for addon in addons_to_modify],
                *[[str(addon.pk)] for addon in addons_to_ignore_promoted],
            ]
        )

        call_command('force_min_android_compatibility', csv_path)

        for addon in addons_to_modify:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID in addon.current_version.compatible_apps
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].min.version
                == '120.0'
            )
            assert addon.current_version.compatible_apps[amo.ANDROID].max.version == '*'
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].originated_from
                == amo.APPVERSIONS_ORIGINATED_FROM_MIGRATION
            )
            assert not addon.current_version.file.reload().strict_compatibility

        for addon in addons_to_ignore_promoted:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID in addon.current_version.compatible_apps
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].min.version == '48.0'
            )
            assert addon.current_version.compatible_apps[amo.ANDROID].max.version == '*'
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].originated_from
                == amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN
            )
            assert not addon.current_version.file.reload().strict_compatibility

        for addon in addons_to_ignore_not_in_csv:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID not in addon.current_version.compatible_apps


class TestDropCompatibilityCommand(TestCase):
    def setUp(self):
        self.min_version_fenix = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )[0]
        self.max_version_fenix = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
        )[0]

    def _create_csv(self, contents):
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False
        ) as csv_file:
            self.addCleanup(os.remove, csv_file.name)
            writer = csv.writer(csv_file)
            writer.writerows(contents)
        return csv_file.name

    def test_handle(self):
        addons_to_drop = [
            addon_factory(),
            addon_factory(),
            addon_factory(version_kw={'application': amo.ANDROID.id}),
        ]
        ApplicationsVersions.objects.create(
            version=addons_to_drop[0].current_version,
            application=amo.ANDROID.id,
            min=self.min_version_fenix,
            max=self.max_version_fenix,
        )
        version_factory(addon=addons_to_drop[-1], application=amo.ANDROID.id)
        addons_to_ignore = [
            addon_factory(),
            addon_factory(version_kw={'application': amo.ANDROID.id}),
        ]
        ApplicationsVersions.objects.create(
            version=addons_to_ignore[0].current_version,
            application=amo.ANDROID.id,
            min=self.min_version_fenix,
            max=self.max_version_fenix,
        )
        version_factory(addon=addons_to_ignore[-1], application=amo.ANDROID.id)
        csv_path = self._create_csv(
            [
                ['addon_id'],
                *[[str(addon.pk)] for addon in addons_to_drop],
            ]
        )
        call_command('drop_android_compatibility', csv_path)
        for addon in addons_to_drop:
            for version in addon.versions.all():
                if hasattr(version, '_compatible_apps'):
                    del version._compatible_apps
                assert amo.ANDROID not in version.compatible_apps

        for addon in addons_to_ignore:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID in addon.current_version.compatible_apps


class TestBumpMinAndroidCompatibility(TestCase):
    # Force MIN_VERSION_FENIX_GENERAL_AVAILABILITY to 119.0a1 so that we can
    # set the ApplicationsVersions to that value in the test data we're
    # creating. It's overridden below when triggering call_command().
    @mock.patch.object(amo, 'MIN_VERSION_FENIX_GENERAL_AVAILABILITY', '119.0a1')
    def test_basic(self):
        AppVersion.objects.get_or_create(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )
        new_min_android_ga_version = '121.0a1'
        AppVersion.objects.get_or_create(
            application=amo.ANDROID.id,
            version=new_min_android_ga_version,
        )

        recommended_addon_with_multiple_versions = addon_factory(
            version_kw={
                'application': amo.ANDROID.id,
                'min_app_version': '119.0a1',
                'max_app_version': '*',
            },
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
        )

        to_bump = [
            # Higher than new_min_android_ga_version, will be adjusted down.
            addon_factory(
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '121.0a1',
                    'max_app_version': '*',
                }
            ).current_version,
            # Lower than new_min_android_ga_version, will be adjusted up.
            addon_factory(
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '119.0a1',
                    'max_app_version': '*',
                }
            ).current_version,
            recommended_addon_with_multiple_versions.current_version,
        ]

        to_ignore = [
            # Not even compatible with Android.
            addon_factory().current_version,
            # That version of not compatible with a version high enough for us
            # to care.
            version_factory(
                addon=recommended_addon_with_multiple_versions,
                application=amo.ANDROID.id,
                min_app_version='113.0',
                max_app_version='*',
                promotion_approved=True,
            ),
        ]

        with mock.patch.object(
            amo, 'MIN_VERSION_FENIX_GENERAL_AVAILABILITY', new_min_android_ga_version
        ):
            call_command('bump_min_android_compatibility')

        for version in to_bump:
            if hasattr(version, '_compatible_apps'):
                del version._compatible_apps
            assert amo.ANDROID in version.compatible_apps
        assert version.compatible_apps[amo.ANDROID].min.application == amo.ANDROID.id
        assert (
            version.compatible_apps[amo.ANDROID].min.version
            == new_min_android_ga_version
        )

        for version in to_ignore:
            if hasattr(version, '_compatible_apps'):
                del version._compatible_apps
            if amo.ANDROID in version.compatible_apps:
                assert version.compatible_apps[
                    amo.ANDROID
                ].min.version_int < version_int(new_min_android_ga_version)


class TestProcessVersions(TestCase):
    def test_block_old_deleted_versions(self):
        user_factory(pk=settings.TASK_USER_ID)
        deleted_addon = addon_factory(
            status=amo.STATUS_DELETED,
            version_kw={'deleted': True},
            file_kw={'status': amo.STATUS_DISABLED},
        )
        addon_with_two_versions = addon_factory(
            version_kw={'deleted': True}, file_kw={'status': amo.STATUS_DISABLED}
        )
        version_factory(
            addon=addon_with_two_versions,
            deleted=True,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        # should be ignored:
        blocked_addon = addon_factory(
            version_kw={'deleted': True}, file_kw={'status': amo.STATUS_DISABLED}
        )
        existing_block = Block.objects.create(
            guid=blocked_addon.guid, updated_by=user_factory()
        )
        BlockVersion.objects.create(
            block=existing_block,
            version=blocked_addon.versions(manager='unfiltered_for_relations').get(),
        )
        addon_factory()
        assert (
            Version.unfiltered.filter(deleted=True, blockversion__id=None).count() == 3
        )

        call_command(
            'process_versions', task='block_old_deleted_versions', with_deleted=True
        )

        new_blocks = list(Block.objects.exclude(id=existing_block.id))
        assert len(new_blocks) == 2
        assert new_blocks[0].guid == addon_with_two_versions.guid
        assert (
            new_blocks[0].blockversion_set.all()[1].version
            == addon_with_two_versions.versions(
                manager='unfiltered_for_relations'
            ).all()[0]
        )
        assert (
            new_blocks[0].blockversion_set.all()[0].version
            == addon_with_two_versions.versions(
                manager='unfiltered_for_relations'
            ).all()[1]
        )
        assert new_blocks[1].guid == deleted_addon.guid
        assert (
            new_blocks[1].blockversion_set.get().version
            == deleted_addon.versions(manager='unfiltered_for_relations').get()
        )

        assert (
            BlockVersion.objects.filter(block_type=BlockType.SOFT_BLOCKED).count() == 3
        )
        assert BlockVersion.objects.filter(block_type=BlockType.BLOCKED).count() == 1
