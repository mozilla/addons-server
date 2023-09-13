import csv
import os
import tempfile
from datetime import datetime

from django.core.management import call_command
from django.core.management.base import CommandError

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory
from olympia.applications.models import AppVersion
from olympia.constants.promoted import LINE, RECOMMENDED
from olympia.files.models import File
from olympia.versions.management.commands.force_min_android_compatibility import (
    Command as ForceMinAndroidCompatibility,
)
from olympia.versions.models import ApplicationsVersions


class TestForceMinAndroidCompatibility(TestCase):
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

    def test_missing_csv_path(self):
        with self.assertRaises(CommandError):
            call_command('force_min_android_compatibility')

    def test_init_csv_parsing(self):
        file_working_name = self._create_csv(
            [['addon_id'], ['123456789'], ['4815162342'], ['007'], ['42']]
        )
        command = ForceMinAndroidCompatibility()
        assert command.read_csv(file_working_name) == [123456789, 4815162342, 7, 42]

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
                promoted=RECOMMENDED,
            ),
            addon_factory(
                name='Line for all',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
                promoted=LINE,
            ),
        ]
        addons_to_ignore_not_in_csv = [addon_factory(name='Not in csv')]
        csv_path = self._create_csv(
            [
                ['addon_id'],
                *[[str(addon.pk)] for addon in addons_to_modify],
                *[[str(addon.pk) for addon in addons_to_ignore_promoted]],
            ]
        )

        call_command('force_min_android_compatibility', csv_path)

        for addon in addons_to_modify:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID in addon.current_version.compatible_apps
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].min.version
                == '119.0a1'
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


class TestForceMaxAndroidCompatibility(TestCase):
    def setUp(self):
        self.min_version_fenix = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )[0]
        self.max_version_fenix = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version=amo.MAX_VERSION_FENNEC
        )[0]
        self.some_fenix_version = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='99.0'
        )[0]

    def test_full(self):
        addons_to_ignore_promoted = [
            addon_factory(
                name='Recommended for Android',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
                promoted=RECOMMENDED,
            ),
            addon_factory(
                name='Line for all',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
                promoted=LINE,
            ),
        ]
        addons_to_ignore_119 = [
            addon_factory(
                name='Recommended for Android 119',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '119.0a1',
                    'max_app_version': '*',
                },
                promoted=RECOMMENDED,
            ),
            addon_factory(
                name='Normal for Android 119',
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '119.0a1',
                    'max_app_version': '*',
                },
                promoted=RECOMMENDED,
            ),
        ]
        addons_to_ignore_not_even_listed_extension = [
            addon_factory(
                name='Theme for Android (!)',
                type=amo.ADDON_STATICTHEME,
                version_kw={
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
            ),
            addon_factory(
                name='Unlisted Extension for Android',
                version_kw={
                    'channel': amo.CHANNEL_UNLISTED,
                    # Can't be set like that, fixed below.
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
            ),
        ]
        addons_to_ignore_not_even_compatible_with_android = [
            addon_factory(
                name='Extension for Firefox',
                version_kw={
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
            ),
        ]
        addons = [
            addon_factory(
                name='Normal extension for Android 48',
                version_kw={
                    # Can't be set like that, fixed below.
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
            ),
        ]
        addons_to_drop = [
            addon_factory(
                name='Normal extension for Android 99.0',
                version_kw={
                    # Can't be set like that, fixed below.
                    'application': amo.ANDROID.id,
                    'min_app_version': '48.0',
                    'max_app_version': '*',
                },
            ),
        ]
        # Directly creating an add-on compatible with Firefox for Android 99.0
        # is no longer possible without being recommended, so manually update
        # some ApplicationsVersions that we couldn't set.
        ApplicationsVersions.objects.filter(
            pk=addons_to_drop[0].current_version.compatible_apps[amo.ANDROID].pk
        ).update(min=self.some_fenix_version)
        ApplicationsVersions.objects.filter(
            pk=addons_to_ignore_not_even_listed_extension[1]
            .versions.get()
            .compatible_apps[amo.ANDROID]
            .pk
        ).update(min=AppVersion.objects.get(application=amo.ANDROID.id, version='48.0'))
        ApplicationsVersions.objects.filter(
            pk=addons[0].current_version.compatible_apps[amo.ANDROID].pk
        ).update(min=AppVersion.objects.get(application=amo.ANDROID.id, version='48.0'))

        call_command('force_max_android_compatibility')

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

        for addon in addons_to_ignore_119:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID in addon.current_version.compatible_apps
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].min.version
                == '119.0a1'
            )
            assert addon.current_version.compatible_apps[amo.ANDROID].max.version == '*'
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].originated_from
                == amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN
            )
            assert not addon.current_version.file.reload().strict_compatibility

        for addon in addons_to_ignore_not_even_listed_extension:
            version = addon.versions.get()
            assert amo.ANDROID in version.compatible_apps
            assert version.compatible_apps[amo.ANDROID].min.version == '48.0'
            assert version.compatible_apps[amo.ANDROID].max.version == '*'
            assert (
                version.compatible_apps[amo.ANDROID].originated_from
                == amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN
            )
            assert not version.file.reload().strict_compatibility

        for addon in addons_to_ignore_not_even_compatible_with_android:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID not in addon.current_version.compatible_apps
            assert (
                addon.current_version.compatible_apps[amo.FIREFOX].originated_from
                == amo.APPVERSIONS_ORIGINATED_FROM_UNKNOWN
            )
            assert not addon.current_version.file.reload().strict_compatibility

        for addon in addons:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID in addon.current_version.compatible_apps
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].min.version == '48.0'
            )
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].max.version == '68.*'
            )
            assert (
                addon.current_version.compatible_apps[amo.ANDROID].originated_from
                == amo.APPVERSIONS_ORIGINATED_FROM_MIGRATION
            )
            assert addon.current_version.file.reload().strict_compatibility

        for addon in addons_to_drop:
            if hasattr(addon.current_version, '_compatible_apps'):
                del addon.current_version._compatible_apps
            assert amo.ANDROID not in addon.current_version.compatible_apps
            assert not addon.current_version.file.reload().strict_compatibility
