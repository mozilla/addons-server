import os.path

from datetime import datetime, timedelta

from django.db import transaction
from django.conf import settings
from django.test.testcases import TransactionTestCase

from unittest import mock
import pytest
import waffle

from waffle.testutils import override_switch

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    license_factory,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.applications.models import AppVersion
from olympia.blocklist.models import Block
from olympia.constants.promoted import (
    LINE,
    NOT_PROMOTED,
    RECOMMENDED,
    SPOTLIGHT,
    STRATEGIC,
)
from olympia.constants.scanners import CUSTOMS, WAT, YARA, MAD
from olympia.files.models import File
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon
from olympia.promoted.models import PromotedApproval
from olympia.reviewers.models import AutoApprovalSummary
from olympia.scanners.models import ScannerResult
from olympia.users.models import (
    EmailUserRestriction,
    IPNetworkUserRestriction,
    RESTRICTION_TYPES,
    UserProfile,
)
from olympia.users.utils import get_task_user
from olympia.versions.compare import version_int, VersionString
from olympia.versions.models import (
    ApplicationsVersions,
    DeniedInstallOrigin,
    License,
    InstallOrigin,
    Version,
    VersionCreateError,
    VersionPreview,
    VersionReviewerFlags,
    source_upload_path,
)


pytestmark = pytest.mark.django_db


class TestVersionManager(TestCase):
    def test_latest_public_compatible_with(self):
        # Add compatible add-ons. We're going to request versions compatible
        # with 58.0.
        compatible_pack1 = addon_factory(
            name='Spanish Language Pack',
            type=amo.ADDON_LPAPP,
            target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        compatible_pack1.current_version.update(created=self.days_ago(2))
        compatible_version1 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        compatible_version1.update(created=self.days_ago(1))
        compatible_pack2 = addon_factory(
            name='French Language Pack',
            type=amo.ADDON_LPAPP,
            target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'},
        )
        compatible_version2 = compatible_pack2.current_version
        compatible_version2.update(created=self.days_ago(2))
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0',
            max_app_version='59.*',
        )
        # Add a more recent version for both add-ons, that would be compatible
        # with 58.0, but is not public/listed so should not be returned.
        version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
        )
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True, 'status': amo.STATUS_DISABLED},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        # And for the first pack, add a couple of versions that are also
        # compatible. They are older so should appear after.
        extra_compatible_version_1 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        extra_compatible_version_1.update(created=self.days_ago(3))
        extra_compatible_version_2 = version_factory(
            addon=compatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='58.0',
            max_app_version='58.*',
        )
        extra_compatible_version_2.update(created=self.days_ago(4))

        # Add a few of incompatible add-ons.
        incompatible_pack1 = addon_factory(
            name='German Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP,
            target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '56.0', 'max_app_version': '56.*'},
        )
        version_factory(
            addon=incompatible_pack1,
            file_kw={'strict_compatibility': True},
            min_app_version='59.0',
            max_app_version='59.*',
        )
        addon_factory(
            name='Italian Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP,
            target_locale='it',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '59.0', 'max_app_version': '59.*'},
        )
        # Even add a pack with a compatible version... not public. And another
        # one with a compatible version... not listed.
        incompatible_pack2 = addon_factory(
            name='Japanese Language Pack (public, but 58.0 version is not)',
            type=amo.ADDON_LPAPP,
            target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        version_factory(
            addon=incompatible_pack2,
            min_app_version='58.0',
            max_app_version='58.*',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'strict_compatibility': True,
            },
        )
        incompatible_pack3 = addon_factory(
            name='Nederlands Language Pack (58.0 version is unlisted)',
            type=amo.ADDON_LPAPP,
            target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'},
        )
        version_factory(
            addon=incompatible_pack3,
            min_app_version='58.0',
            max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'strict_compatibility': True},
        )

        appversions = {
            'min': version_int('58.0'),
            'max': version_int('58.0a'),
        }
        qs = Version.objects.latest_public_compatible_with(amo.FIREFOX.id, appversions)

        expected_versions = [
            compatible_version1,
            compatible_version2,
            extra_compatible_version_1,
            extra_compatible_version_2,
        ]
        assert list(qs) == expected_versions

    def test_version_hidden_from_related_manager_after_deletion(self):
        """Test that a version that has been deleted should be hidden from the
        reverse relations, unless using the specific unfiltered_for_relations
        manager."""

        addon = addon_factory()
        version = addon.current_version
        assert addon.versions.get() == version

        # Deleted Version should be hidden from the reverse relation manager.
        version.delete()
        addon = Addon.objects.get(pk=addon.pk)
        assert addon.versions.count() == 0

        # But we should be able to see it using unfiltered_for_relations.
        addon.versions(manager='unfiltered_for_relations').count() == 1
        addon.versions(manager='unfiltered_for_relations').get() == version

    def test_version_still_accessible_from_foreign_key_after_deletion(self):
        """Test that a version that has been deleted should still be accessible
        from a foreign key."""

        version = addon_factory().current_version
        # We use VersionPreview as atm those are kept around, but any other
        # model that has a FK to Version and isn't deleted when a Version is
        # soft-deleted would work.
        version_preview = VersionPreview.objects.create(version=version)
        assert version_preview.version == version

        # Deleted Version should *not* prevent the version from being
        # accessible using the FK.
        version.delete()
        version_preview = VersionPreview.objects.get(pk=version_preview.pk)
        assert version_preview.version == version


class TestVersion(TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super().setUp()
        self.version = Version.objects.get(pk=81551)

    def target_mobile(self):
        app = amo.ANDROID.id
        app_vr = AppVersion.objects.create(application=app, version='1.0')
        ApplicationsVersions.objects.create(
            version=self.version, application=app, min=app_vr, max=app_vr
        )

    def test_compatible_apps(self):
        version = Version.objects.get(pk=81551)

        assert amo.FIREFOX in version.compatible_apps, 'Missing Firefox >_<'

        # We should be re-using the same Version instance in
        # ApplicationsVersions loaded from <Version>._create_compatible_apps().
        assert id(version) == id(version.compatible_apps[amo.FIREFOX].version)

    def _get_version(self, status):
        return addon_factory(file_kw={'status': status}).current_version

    def test_is_unreviewed(self):
        assert self._get_version(amo.STATUS_AWAITING_REVIEW).is_unreviewed
        assert not self._get_version(amo.STATUS_APPROVED).is_unreviewed

    @mock.patch('olympia.versions.tasks.VersionPreview.delete_preview_files')
    def test_version_delete(self, delete_preview_files_mock):
        version = Version.objects.get(pk=81551)
        version_preview = VersionPreview.objects.create(version=version)
        assert version.file
        version.delete()

        addon = Addon.objects.get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert Version.unfiltered.filter(addon=addon).exists()
        assert File.objects.filter(version=version).exists()
        delete_preview_files_mock.assert_called_with(
            sender=None, instance=version_preview
        )

    def test_version_delete_unlisted(self):
        version = Version.objects.get(pk=81551)
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.test_version_delete()

    def test_version_hard_delete(self):
        version = Version.objects.get(pk=81551)
        VersionPreview.objects.create(version=version)
        assert version.file
        version.delete(hard=True)

        addon = Addon.objects.get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert not Version.unfiltered.filter(addon=addon).exists()
        assert not File.objects.filter(version=version).exists()
        assert not VersionPreview.objects.filter(version=version).exists()

    def test_version_delete_logs(self):
        task_user = UserProfile.objects.create(pk=settings.TASK_USER_ID)
        user = UserProfile.objects.get(pk=55021)
        core.set_user(user)
        version = Version.objects.get(pk=81551)
        qs = ActivityLog.objects.all()
        assert qs.count() == 0
        version.delete()
        assert qs.count() == 2
        assert qs[0].action == amo.LOG.CHANGE_STATUS.id
        assert qs[0].user == task_user
        assert qs[1].action == amo.LOG.DELETE_VERSION.id
        assert qs[1].user == user

    def test_version_delete_clear_pending_rejection(self):
        version = Version.objects.get(pk=81551)
        VersionReviewerFlags.objects.create(
            version=version, pending_rejection=datetime.now() + timedelta(days=1)
        )
        flags = VersionReviewerFlags.objects.get(version=version)
        assert flags.pending_rejection
        version.delete()
        flags.reload()
        assert not flags.pending_rejection

    def test_version_disable_and_reenable(self):
        version = Version.objects.get(pk=81551)
        assert version.file.status == amo.STATUS_APPROVED

        version.is_user_disabled = True
        version.file.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert version.file.original_status == amo.STATUS_APPROVED

        version.is_user_disabled = False
        version.file.reload()
        assert version.file.status == amo.STATUS_APPROVED
        assert version.file.original_status == amo.STATUS_NULL

    def test_version_disable_after_mozila_disabled(self):
        # Check that a user disable doesn't override mozilla disable
        version = Version.objects.get(pk=81551)
        version.file.update(status=amo.STATUS_DISABLED)

        version.is_user_disabled = True
        version.file.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert version.file.original_status == amo.STATUS_NULL

        version.is_user_disabled = False
        version.file.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert version.file.original_status == amo.STATUS_NULL

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_new_version_disable_old_unreviewed(self, hide_disabled_file_mock):
        addon = Addon.objects.get(id=3615)
        # The status doesn't change for public files.
        qs = File.objects.filter(version=addon.current_version)
        assert qs.all()[0].status == amo.STATUS_APPROVED
        Version.objects.create(addon=addon)
        assert qs.all()[0].status == amo.STATUS_APPROVED
        assert not hide_disabled_file_mock.called

        qs.update(status=amo.STATUS_AWAITING_REVIEW)
        version = Version.objects.create(addon=addon, version='0.87')
        version.disable_old_files()
        assert qs.all()[0].status == amo.STATUS_DISABLED
        assert hide_disabled_file_mock.called

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_new_version_dont_disable_old_unlisted_unreviewed(
        self, hide_disabled_file_mock
    ):
        addon = Addon.objects.get(id=3615)
        old_version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        new_version = Version.objects.create(addon=addon)
        new_version.disable_old_files()
        assert old_version.file.status == amo.STATUS_AWAITING_REVIEW
        assert not hide_disabled_file_mock.called

        # Doesn't happen even if the new version is also unlisted.
        new_version = Version.objects.create(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED, version='0.54'
        )
        new_version.disable_old_files()
        assert old_version.file.status == amo.STATUS_AWAITING_REVIEW
        assert not hide_disabled_file_mock.called

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_new_version_unlisted_dont_disable_old_unreviewed(
        self, hide_disabled_file_mock
    ):
        addon = Addon.objects.get(id=3615)
        old_version = addon.current_version
        old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)

        version = version_factory(addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        version.disable_old_files()

        old_version.reload()
        assert old_version.file.status == amo.STATUS_AWAITING_REVIEW
        assert not hide_disabled_file_mock.called

    def _reset_version(self, version):
        version.file.status = amo.STATUS_APPROVED
        version.deleted = False

    def test_version_is_public(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)

        # Base test. Everything is in order, the version should be public.
        assert version.is_public()

        # Non-public file.
        self._reset_version(version)
        version.file.status = amo.STATUS_DISABLED
        assert not version.is_public()

        # Deleted version.
        self._reset_version(version)
        version.deleted = True
        assert not version.is_public()

        # Non-public addon.
        self._reset_version(version)

        is_public_path = 'olympia.addons.models.Addon.is_public'
        with mock.patch(is_public_path) as is_addon_public:
            is_addon_public.return_value = False
            assert not version.is_public()

    def test_is_compatible_by_default(self):
        # Base test for fixture before the rest. Should be compatible by
        # default.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        assert version.is_compatible_by_default
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_by_default_type(self):
        # Types in NO_COMPAT are compatible by default.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        addon.update(type=amo.ADDON_DICT)
        assert version.is_compatible_by_default
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_by_default_strict_opt_in(self):
        # Add-ons opting into strict compatibility should not be compatible
        # by default.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        file = version.file
        file.update(strict_compatibility=True)
        assert not version.is_compatible_by_default
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_app_max_version(self):
        # Add-ons with max app version < 4.0 should not be compatible.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon, max_app_version='3.5')
        assert not version.is_compatible_app(amo.FIREFOX)
        # An app that isn't supported should also be False.
        assert not version.is_compatible_app(amo.ANDROID)
        # An app that can't do d2c should also be False.
        assert not version.is_compatible_app(amo.UNKNOWN_APP)

    def test_get_url_path(self):
        assert self.version.get_url_path() == ('/en-US/firefox/addon/a3615/versions/')

    def test_valid_versions(self):
        addon = Addon.objects.get(id=3615)
        additional_version = version_factory(addon=addon, version='0.1')
        version_factory(
            addon=addon, version='0.2', file_kw={'status': amo.STATUS_DISABLED}
        )
        assert list(Version.objects.valid()) == [additional_version, self.version]

    def test_unlisted_addon_get_url_path(self):
        self.make_addon_unlisted(self.version.addon)
        self.version.reload()
        assert self.version.get_url_path() == ''

    def test_source_upload_path(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'foo.tar.gz')
        assert uploaded_name.endswith('a3615-0.1-src.tar.gz')

    def test_source_upload_path_utf8_chars(self):
        addon = Addon.objects.get(id=3615)
        addon.update(slug='crosswarpex-확장')
        version = version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'crosswarpex-확장.tar.gz')
        assert uploaded_name.endswith('crosswarpex-확장-0.1-src.tar.gz')

    def test_is_ready_for_auto_approval(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version.update(channel=amo.RELEASE_CHANNEL_LISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # With the auto-approval disabled flag set, it's still considered
        # "ready", even though the auto_approve code won't approve it.
        del version.is_ready_for_auto_approval
        AddonReviewerFlags.objects.create(addon=addon, auto_approval_disabled=False)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_STATICTHEME)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_LPAPP)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_DICT)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # Test with an unlisted version. Note that it's the only version, so
        # the add-on status is reset to STATUS_NULL at this point.
        del version.is_ready_for_auto_approval
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # Retest with an unlisted version again and the addon being approved or
        # nominated
        del version.is_ready_for_auto_approval
        addon.reload()
        addon.update(status=amo.STATUS_NOMINATED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(status=amo.STATUS_APPROVED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

    def test_is_ready_for_auto_approval_addon_status(self):
        addon = Addon.objects.get(id=3615)
        addon.status = amo.STATUS_NOMINATED
        version = addon.current_version
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        addon.update(status=amo.STATUS_DISABLED)
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

    def test_transformer_auto_approvable(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        del version.is_ready_for_auto_approval
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version.update(channel=amo.RELEASE_CHANNEL_LISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__

        # With the auto-approval disabled flag set, it's still considered
        # "ready", even though the auto_approve code won't approve it.
        del version.is_ready_for_auto_approval
        AddonReviewerFlags.objects.create(addon=addon, auto_approval_disabled=False)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_STATICTHEME)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert not version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_LPAPP)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(type=amo.ADDON_DICT)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        # Test with an unlisted version. Note that it's the only version, so
        # the add-on status is reset to STATUS_NULL at this point.
        del version.is_ready_for_auto_approval
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        # Retest with an unlisted version again and the addon being approved or
        # nominated
        del version.is_ready_for_auto_approval
        addon.reload()
        addon.update(status=amo.STATUS_NOMINATED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

        del version.is_ready_for_auto_approval
        addon.update(status=amo.STATUS_APPROVED)
        # Ensure the cached_property has not been set yet
        assert 'is_ready_for_auto_approval' not in version.__dict__
        # Set it.
        Version.transformer_auto_approvable([version])
        # It should now be set
        assert 'is_ready_for_auto_approval' in version.__dict__
        # Test it.
        assert version.is_ready_for_auto_approval

    def test_was_auto_approved(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert not version.was_auto_approved

        AutoApprovalSummary.objects.create(version=version, verdict=amo.AUTO_APPROVED)
        assert version.was_auto_approved

        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        assert not version.was_auto_approved

    def test_transformer_license(self):
        addon = Addon.objects.get(id=3615)
        version1 = version_factory(addon=addon)
        license = license_factory(name='Second License', text='Second License Text')
        version2 = version_factory(addon=addon, license=license)

        qs = Version.objects.filter(pk__in=(version1.pk, version2.pk)).no_transforms()
        with self.assertNumQueries(5):
            # - 1 for the versions
            # - 2 for the licenses (1 for each version)
            # - 2 for the licenses translations (1 for each version)
            for version in qs.all():
                assert version.license.name

        # Using the transformer should prefetch licenses and name translations.
        # License text should be deferred.
        with self.assertNumQueries(3):
            # - 1 for the versions
            # - 1 for the licenses
            # - 1 for the licenses translations (name)
            for version in qs.transform(Version.transformer_license).all():
                assert 'text_id' in version.license.get_deferred_fields()
                assert version.license.name

    @mock.patch('olympia.amo.tasks.trigger_sync_objects_to_basket')
    def test_version_field_changes_not_synced_to_basket(
        self, trigger_sync_objects_to_basket_mock
    ):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(
            approval_notes='Flôp',
            reviewed=self.days_ago(1),
            nomination=self.days_ago(2),
            version='1.42',
        )
        assert trigger_sync_objects_to_basket_mock.call_count == 0

    @mock.patch('olympia.amo.tasks.trigger_sync_objects_to_basket')
    def test_version_promoted_changes_synced_to_basket(
        self, trigger_sync_objects_to_basket_mock
    ):
        addon = Addon.objects.get(id=3615)
        PromotedApproval.objects.create(
            version=addon.current_version,
            group_id=RECOMMENDED.id,
            application_id=amo.FIREFOX.id,
        )
        assert trigger_sync_objects_to_basket_mock.call_count == 1
        trigger_sync_objects_to_basket_mock.assert_called_with(
            'addon', [addon.pk], 'promoted change'
        )

    @mock.patch('olympia.amo.tasks.trigger_sync_objects_to_basket')
    def test_unlisted_version_deleted_synced_to_basket(
        self, trigger_sync_objects_to_basket_mock
    ):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        trigger_sync_objects_to_basket_mock.reset_mock()

        version.delete()
        assert trigger_sync_objects_to_basket_mock.call_count == 1
        trigger_sync_objects_to_basket_mock.assert_called_with(
            'addon', [addon.pk], 'unlisted version deleted'
        )

    @mock.patch('olympia.amo.tasks.trigger_sync_objects_to_basket')
    def test_version_deleted_not_synced_to_basket(
        self, trigger_sync_objects_to_basket_mock
    ):
        addon = Addon.objects.get(id=3615)
        # We need to create a new version, if we delete current_version this
        # would be synced to basket because _current_version would change.
        new_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_NOMINATED}
        )
        new_version.delete()
        assert trigger_sync_objects_to_basket_mock.call_count == 0

    def test_promoted_can_be_disabled_and_deleted(self):
        addon = Addon.objects.get(id=3615)
        # A non-promoted addon can have it's versions disabled.
        assert addon.current_version.can_be_disabled_and_deleted()

        self.make_addon_promoted(addon, RECOMMENDED, approve_version=True)
        addon = addon.reload()
        assert addon.promoted_group() == RECOMMENDED
        # But a promoted one, that's in a prereview group, can't be disabled
        assert not addon.current_version.can_be_disabled_and_deleted()

        previous_version = addon.current_version
        version_factory(addon=addon, promotion_approved=True)
        addon = addon.reload()
        assert previous_version != addon.current_version
        assert addon.current_version.promoted_approvals.filter(
            group_id=RECOMMENDED.id
        ).exists()
        assert previous_version.promoted_approvals.filter(
            group_id=RECOMMENDED.id
        ).exists()
        # unless the previous version is also approved for the same group
        assert addon.current_version.can_be_disabled_and_deleted()
        assert previous_version.can_be_disabled_and_deleted()

        # double-check by changing the approval of previous version
        previous_version.promoted_approvals.update(group_id=LINE.id)
        assert not addon.current_version.can_be_disabled_and_deleted()
        previous_version.promoted_approvals.update(group_id=RECOMMENDED.id)

        # Check the scenario when some of the previous versions are approved
        # but not the most recent previous - i.e. the one that would become the
        # new current_version.
        version_a = previous_version.reload()
        version_b = addon.current_version
        version_c = version_factory(addon=addon)
        version_d = version_factory(addon=addon, promotion_approved=True)
        version_c.is_user_disabled = True  # disabled version_c
        addon = addon.reload()
        version_b = version_b.reload()
        assert version_d == addon.current_version
        assert version_a.promoted_approvals.filter(group_id=RECOMMENDED.id).exists()
        assert version_b.promoted_approvals.filter(group_id=RECOMMENDED.id).exists()
        # ignored because disabled
        assert not version_c.promoted_approvals.filter(group_id=RECOMMENDED.id).exists()
        assert version_d.promoted_approvals.filter(group_id=RECOMMENDED.id).exists()
        assert version_a.can_be_disabled_and_deleted()
        assert version_b.can_be_disabled_and_deleted()
        assert version_c.can_be_disabled_and_deleted()
        assert version_d.can_be_disabled_and_deleted()
        assert addon.promoted_group() == RECOMMENDED
        # now un-approve version_b
        version_b.promoted_approvals.update(group_id=NOT_PROMOTED.id)
        assert version_a.can_be_disabled_and_deleted()
        assert version_b.can_be_disabled_and_deleted()
        assert version_c.can_be_disabled_and_deleted()
        assert not version_d.can_be_disabled_and_deleted()
        assert addon.promoted_group() == RECOMMENDED

    def test_unbadged_non_prereview_promoted_can_be_disabled_and_deleted(self):
        addon = Addon.objects.get(id=3615)
        self.make_addon_promoted(addon, LINE, approve_version=True)
        assert addon.promoted_group() == LINE
        # it's the only version of a group that requires pre-review and is
        # badged, so can't be deleted.
        assert not addon.current_version.can_be_disabled_and_deleted()

        # STRATEGIC isn't pre-reviewd or badged, so it's okay though
        addon.promotedaddon.update(group_id=STRATEGIC.id)
        addon.current_version.promoted_approvals.update(group_id=STRATEGIC.id)
        del addon.current_version.approved_for_groups
        assert addon.promoted_group() == STRATEGIC
        assert addon.current_version.can_be_disabled_and_deleted()

        # SPOTLIGHT is pre-reviewed but not badged, so it's okay too
        addon.promotedaddon.update(group_id=SPOTLIGHT.id)
        addon.current_version.promoted_approvals.update(group_id=SPOTLIGHT.id)
        assert addon.promoted_group() == SPOTLIGHT
        assert addon.current_version.can_be_disabled_and_deleted()

    def test_can_be_disabled_and_deleted_querycount(self):
        addon = Addon.objects.get(id=3615)
        version_factory(addon=addon)
        self.make_addon_promoted(addon, RECOMMENDED, approve_version=True)
        addon.reload()
        with self.assertNumQueries(3):
            # 1. check the addon's promoted group
            # 2. check addon.current_version is approved for that group
            # 3. check the previous version is approved for that group
            assert not addon.current_version.can_be_disabled_and_deleted()

    def test_is_blocked(self):
        addon = Addon.objects.get(id=3615)
        assert addon.current_version.is_blocked is False

        block = Block.objects.create(addon=addon, updated_by=user_factory())
        assert Addon.objects.get(id=3615).current_version.is_blocked is True

        block.update(min_version='999999999')
        assert Addon.objects.get(id=3615).current_version.is_blocked is False

        block.update(min_version='0')
        assert Addon.objects.get(id=3615).current_version.is_blocked is True

    def test_pending_rejection_property(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # No flags: None
        assert version.pending_rejection is None
        # Flag present, value is None (default): None.
        flags = VersionReviewerFlags.objects.create(version=version)
        assert flags.pending_rejection is None
        assert version.pending_rejection is None
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(pending_rejection=in_the_past)
        assert version.pending_rejection == in_the_past

    def test_pending_rejection_by_property(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = user_factory()
        # No flags: None
        assert version.pending_rejection_by is None
        # Flag present, value is None (default): None.
        flags = VersionReviewerFlags.objects.create(version=version)
        assert flags.pending_rejection_by is None
        assert version.pending_rejection_by is None
        # Flag present, value is a user.
        flags.update(pending_rejection=self.days_ago(1), pending_rejection_by=user)
        assert version.pending_rejection_by == user

    def test_pending_rejection_by_cleared_when_pending_rejection_cleared(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = user_factory()
        flags = VersionReviewerFlags.objects.create(
            version=version,
            pending_rejection=self.days_ago(1),
            pending_rejection_by=user,
        )
        assert flags.pending_rejection
        assert flags.pending_rejection_by == user
        assert not flags.needs_human_review_by_mad

        # Update, but do not clear pending_rejection. Both should remain.
        flags.update(needs_human_review_by_mad=True)
        assert flags.pending_rejection
        assert flags.pending_rejection_by == user

        # Clear pending_rejection. pending_rejection_by should be cleared as well.
        flags.update(pending_rejection=None)
        assert flags.pending_rejection is None
        assert flags.pending_rejection_by is None

    def test_needs_human_review_by_mad(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        # No flags: False
        assert not version.needs_human_review_by_mad
        # Flag present, value is None (default): False.
        flags = VersionReviewerFlags.objects.create(version=version)
        assert not version.needs_human_review_by_mad
        # Flag present.
        flags.update(needs_human_review_by_mad=True)
        assert version.needs_human_review_by_mad

    def test_maliciousness_score(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert version.maliciousness_score == 0
        ScannerResult.objects.create(version=version, scanner=MAD, score=0.15)
        assert version.maliciousness_score == 15
        # In case of an error, we'll likely receive a -1.
        version_2 = version_factory(addon=addon)
        ScannerResult.objects.create(version=version_2, scanner=MAD, score=-1)
        assert version_2.maliciousness_score == 0

    def test_approved_for_groups(self):
        version = addon_factory().current_version
        assert version.approved_for_groups == []

        # give it some promoted approvals
        PromotedApproval.objects.create(
            version=version, group_id=LINE.id, application_id=amo.FIREFOX.id
        )
        PromotedApproval.objects.create(
            version=version, group_id=RECOMMENDED.id, application_id=amo.ANDROID.id
        )

        del version.approved_for_groups
        assert version.approved_for_groups == [
            (LINE, amo.FIREFOX),
            (RECOMMENDED, amo.ANDROID),
        ]

    def test_transform_promoted(self):
        version_a = addon_factory().current_version
        version_b = addon_factory().current_version
        versions = Version.objects.filter(
            id__in=(version_a.id, version_b.id)
        ).transform(Version.transformer_promoted)
        list(versions)  # to evaluate the queryset
        with self.assertNumQueries(0):
            assert versions[0].approved_for_groups == []
            assert versions[1].approved_for_groups == []

        # give them some promoted approvals
        PromotedApproval.objects.create(
            version=version_a, group_id=LINE.id, application_id=amo.FIREFOX.id
        )
        PromotedApproval.objects.create(
            version=version_a, group_id=RECOMMENDED.id, application_id=amo.FIREFOX.id
        )
        PromotedApproval.objects.create(
            version=version_b, group_id=RECOMMENDED.id, application_id=amo.FIREFOX.id
        )
        PromotedApproval.objects.create(
            version=version_b, group_id=RECOMMENDED.id, application_id=amo.ANDROID.id
        )

        versions = Version.objects.filter(
            id__in=(version_a.id, version_b.id)
        ).transform(Version.transformer_promoted)
        list(versions)  # to evaluate the queryset
        with self.assertNumQueries(0):
            assert versions[1].approved_for_groups == [
                (RECOMMENDED, amo.FIREFOX),
                (LINE, amo.FIREFOX),
            ]
            assert versions[0].approved_for_groups == [
                (RECOMMENDED, amo.FIREFOX),
                (RECOMMENDED, amo.ANDROID),
            ]

    def test_version_string(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert isinstance(version.version, VersionString)
        assert version.version == '2.1.072'
        assert version.version == '2.1.72.0'  # VersionString magic
        assert version.version > '2.1.072pre'
        # works after an update
        version.update(version=VersionString('2.00123'))
        assert isinstance(version.version, VersionString)
        assert version.version == '2.00123'
        assert version.version == '2.123.0.0'
        assert version.version > '2.00123a4'
        # updating a flat string still works
        version.update(version='3.3')
        assert isinstance(version.version, VersionString)
        assert version.version == '3.03.0'
        version = version.reload()
        assert isinstance(version.version, VersionString)
        assert version.version == '3.03.0'
        # and directly assigning to the field and saving too
        version.version = '5.1b4'
        assert isinstance(version.version, VersionString)
        version.save()
        assert isinstance(version.version, VersionString)
        version = version.reload()
        assert version.version == '5.1b4'

    def test_version_kept_when_license_deleted(self):
        license = License.objects.create(name='MyLicense')
        self.version.update(license=license)
        license.delete()
        assert not License.objects.filter(pk=license.pk).exists()
        assert Version.objects.filter(pk=self.version.pk).exists()


@pytest.mark.parametrize(
    'addon_status,file_status,is_unreviewed',
    [
        (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, True),
        (amo.STATUS_NOMINATED, amo.STATUS_NOMINATED, True),
        (amo.STATUS_NOMINATED, amo.STATUS_APPROVED, False),
        (amo.STATUS_NOMINATED, amo.STATUS_DISABLED, False),
        (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW, True),
        (amo.STATUS_APPROVED, amo.STATUS_NOMINATED, True),
        (amo.STATUS_APPROVED, amo.STATUS_APPROVED, False),
        (amo.STATUS_APPROVED, amo.STATUS_DISABLED, False),
    ],
)
def test_unreviewed_files(db, addon_status, file_status, is_unreviewed):
    """Files that need to be reviewed are returned by version.unreviewed_files."""
    addon = amo.tests.addon_factory(status=addon_status, guid='foo')
    version = addon.current_version
    file_ = version.file
    file_.update(status=file_status)
    # If the addon is public, and we change its only file to something else
    # than public, it'll change to unreviewed.
    addon.update(status=addon_status)
    assert addon.reload().status == addon_status
    assert file_.reload().status == file_status


class TestVersionFromUpload(UploadMixin, TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.upload = self.get_upload(self.filename)
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(guid='@webextension-guid')
        self.selected_app = amo.FIREFOX.id
        self.dummy_parsed_data = {'version': '0.1'}
        self.fake_user = user_factory()


class TestExtensionVersionFromUpload(TestVersionFromUpload):
    filename = 'webextension.xpi'

    def setUp(self):
        super().setUp()

    def test_notified_about_auto_approval_delay_flag_is_reset(self):
        flags = AddonReviewerFlags.objects.create(
            addon=self.addon, notified_about_auto_approval_delay=True
        )
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version
        flags.reload()
        assert flags.notified_about_auto_approval_delay is False

    def test_upload_already_attached_to_different_addon(self):
        # The exception isn't necessarily caught, but it's fine to 500 and go
        # to Sentry in this case - this isn't supposed to happen.
        self.upload.update(addon=addon_factory())
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_addon_disabled(self):
        # The exception isn't necessarily caught, but it's fine to 500 and go
        # to Sentry in this case - this isn't supposed to happen.
        self.addon.update(status=amo.STATUS_DISABLED)
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_addon_is_attached_to_upload_if_it_wasnt(self):
        assert self.upload.addon is None
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version
        self.upload.reload()
        assert self.upload.addon == self.addon

    def test_from_upload_no_user(self):
        self.upload.user = None
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_from_upload_no_ip_address(self):
        self.upload.ip_address = None
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    def test_from_upload_no_source(self):
        self.upload.source = None
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

    @mock.patch('olympia.versions.models.log')
    def test_logging(self, log_mock):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        user.update(last_login_ip='1.2.3.4')
        self.upload.update(
            user=user,
            ip_address='5.6.7.8',
            source=amo.UPLOAD_SOURCE_SIGNING_API,
        )
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert log_mock.info.call_count == 2
        assert log_mock.info.call_args_list[0][0] == (
            (f'New version: {version!r} ({version.pk}) from {self.upload!r}'),
        )
        assert log_mock.info.call_args_list[0][1] == {
            'extra': {
                'email': user.email,
                'guid': self.addon.guid,
                'upload': self.upload.uuid.hex,
                'user_id': user.pk,
                'from_api': True,
            }
        }
        task_user = get_task_user()
        assert ActivityLog.objects.count() == 2
        activities = ActivityLog.objects.all()
        assert activities[0].action == amo.LOG.CHANGE_STATUS.id
        assert activities[0].arguments == [self.addon, amo.STATUS_APPROVED]
        assert activities[0].user == task_user
        assert activities[1].action == amo.LOG.ADD_VERSION.id
        assert activities[1].arguments == [version, self.addon]
        assert activities[1].user == user

    def test_carry_over_old_license(self):
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version.license_id == self.addon.current_version.license_id

    def test_mozilla_signed_extension(self):
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version.is_mozilla_signed
        assert version.approval_notes == (
            'This version has been signed with Mozilla internal certificate.'
        )

    def test_carry_over_license_no_version(self):
        self.addon.versions.all().delete()
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert version.license_id is None

    def test_app_versions(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '42.0'
        assert app.max.version == '*'

    def test_compatibility_just_app(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            compatibility={
                amo.FIREFOX: ApplicationsVersions(application=amo.FIREFOX.id)
            },
            parsed_data=parsed_data,
        )
        assert [amo.FIREFOX] == list(version.compatible_apps)
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '42.0'
        assert app.max.version == '*'

    def test_compatibility_min_max_too(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            compatibility={
                amo.ANDROID: ApplicationsVersions(
                    application=amo.ANDROID.id,
                    min=AppVersion.objects.get_or_create(
                        application=amo.ANDROID.id, version='45.0'
                    )[0],
                    max=AppVersion.objects.get_or_create(
                        application=amo.ANDROID.id, version='67'
                    )[0],
                )
            },
            parsed_data=parsed_data,
        )
        assert [amo.ANDROID] == list(version.compatible_apps)
        app = version.compatible_apps[amo.ANDROID]
        assert app.min.version == '45.0'
        assert app.max.version == '67'

    def test_compatible_apps_is_pre_generated(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        # We mock File.from_upload() to prevent it from accessing
        # version.compatible_apps early - we want to test that the cache has
        # been generated regardless.

        def fake_file(*args, **kwargs):
            return File(version=kwargs['version'])

        with mock.patch('olympia.files.models.File.from_upload', side_effect=fake_file):
            version = Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=parsed_data,
            )
        # Add an extra ApplicationsVersions. It should *not* appear in
        # version.compatible_apps, because that's a cached_property.
        new_app_vr_min = AppVersion.objects.create(
            application=amo.ANDROID.id, version='1.0'
        )
        new_app_vr_max = AppVersion.objects.create(
            application=amo.ANDROID.id, version='2.0'
        )
        ApplicationsVersions.objects.create(
            version=version,
            application=amo.ANDROID.id,
            min=new_app_vr_min,
            max=new_app_vr_max,
        )
        assert amo.ANDROID not in version.compatible_apps
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '42.0'
        assert app.max.version == '*'

    def test_version_number(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.version == '0.0.1'

    def test_file_name(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.file.filename == 'delicious_bookmarks-0.0.1-fx.xpi'

    def test_track_upload_time(self):
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload.update(created=datetime.now() - timedelta(days=1))

        mock_timing_path = 'olympia.versions.models.statsd.timing'
        with mock.patch(mock_timing_path) as mock_timing:
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[self.selected_app],
                parsed_data=self.dummy_parsed_data,
            )

            upload_start = utc_millesecs_from_epoch(self.upload.created)
            now = utc_millesecs_from_epoch()
            rough_delta = now - upload_start
            actual_delta = mock_timing.call_args[0][1]

            fuzz = 2000  # 2 seconds
            assert actual_delta >= (rough_delta - fuzz) and actual_delta <= (
                rough_delta + fuzz
            )

    def test_nomination_inherited_for_updates(self):
        assert self.addon.status == amo.STATUS_APPROVED
        self.addon.current_version.update(nomination=self.days_ago(2))
        pending_version = version_factory(
            addon=self.addon,
            nomination=self.days_ago(1),
            version='9.9',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        assert pending_version.nomination
        upload_version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert upload_version.nomination == pending_version.nomination

    @mock.patch('olympia.amo.tasks.trigger_sync_objects_to_basket')
    def test_from_upload_unlisted_synced_with_basket(
        self, trigger_sync_objects_to_basket_mock
    ):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=parsed_data,
        )
        # It's a new unlisted version, we should be syncing the add-on with
        # basket.
        assert trigger_sync_objects_to_basket_mock.call_count == 1
        trigger_sync_objects_to_basket_mock.assert_called_with(
            'addon', [self.addon.pk], 'new unlisted version'
        )

    @mock.patch('olympia.amo.tasks.trigger_sync_objects_to_basket')
    def test_from_upload_listed_not_synced_with_basket(
        self, trigger_sync_objects_to_basket_mock
    ):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=parsed_data,
        )
        # It's a new listed version, we should *not* be syncing the add-on with
        # basket through version_uploaded signal, but only when
        # _current_version changes, which isn't the case here.
        assert trigger_sync_objects_to_basket_mock.call_count == 0

    def test_set_version_to_customs_scanners_result(self):
        self.create_switch('enable-customs', active=True)
        scanners_result = ScannerResult.objects.create(
            upload=self.upload, scanner=CUSTOMS
        )
        assert scanners_result.version is None

        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        scanners_result.refresh_from_db()
        assert scanners_result.version == version

    def test_set_version_to_wat_scanners_result(self):
        self.create_switch('enable-wat', active=True)
        scanners_result = ScannerResult.objects.create(upload=self.upload, scanner=WAT)
        assert scanners_result.version is None

        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        scanners_result.refresh_from_db()
        assert scanners_result.version == version

    def test_set_version_to_yara_scanners_result(self):
        self.create_switch('enable-yara', active=True)
        scanners_result = ScannerResult.objects.create(upload=self.upload, scanner=YARA)
        assert scanners_result.version is None

        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )

        scanners_result.refresh_from_db()
        assert scanners_result.version == version

    def test_does_nothing_when_no_scanner_is_enabled(self):
        self.create_switch('enable-customs', active=False)
        self.create_switch('enable-wat', active=False)
        self.create_switch('enable-yara', active=False)
        scanners_result = ScannerResult.objects.create(
            upload=self.upload, scanner=CUSTOMS
        )
        assert scanners_result.version is None

        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )

        scanners_result.refresh_from_db()
        assert scanners_result.version is None

    def test_auto_approval_not_disabled_if_not_restricted(self):
        self.upload.user.update(last_login_ip='10.0.0.42')
        # Set a submission time restriction: it shouldn't matter.
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()

    def test_auto_approval_disabled_if_restricted_by_email(self):
        EmailUserRestriction.objects.create(
            email_pattern=self.upload.user.email,
            restriction_type=RESTRICTION_TYPES.APPROVAL,
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.addon.auto_approval_disabled

    def test_auto_approval_disabled_if_restricted_by_ip(self):
        self.upload.user.update(last_login_ip='10.0.0.42')
        IPNetworkUserRestriction.objects.create(
            network='10.0.0.0/24', restriction_type=RESTRICTION_TYPES.APPROVAL
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert self.addon.auto_approval_disabled
        assert not self.addon.auto_approval_disabled_unlisted

    def test_auto_approval_disabled_for_unlisted_if_restricted_by_ip(self):
        self.upload.user.update(last_login_ip='10.0.0.42')
        IPNetworkUserRestriction.objects.create(
            network='10.0.0.0/24', restriction_type=RESTRICTION_TYPES.APPROVAL
        )
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not self.addon.auto_approval_disabled
        assert self.addon.auto_approval_disabled_unlisted

    def test_dont_record_install_origins_when_waffle_switch_is_off(self):
        # Switch should be off by default.
        assert waffle.switch_is_active('record-install-origins') is False
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        parsed_data['install_origins'] = ['https://foo.com', 'https://bar.com']
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.installorigin_set.count() == 0

    @override_switch('record-install-origins', active=True)
    def test_record_install_origins(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        parsed_data['install_origins'] = ['https://foo.com', 'https://bar.com']
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.installorigin_set.count() == 2
        assert sorted(version.installorigin_set.values_list('origin', flat=True)) == [
            'https://bar.com',
            'https://foo.com',
        ]

    @override_switch('record-install-origins', active=True)
    def test_record_install_origins_base_domain(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        parsed_data['install_origins'] = [
            'https://foô.com',
            'https://foo.bar.co.uk',
            'https://foo.bar.栃木.jp',
        ]
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )
        assert version.installorigin_set.count() == 3
        assert sorted(
            version.installorigin_set.values_list('origin', 'base_domain')
        ) == [
            ('https://foo.bar.co.uk', 'bar.co.uk'),
            ('https://foo.bar.栃木.jp', 'bar.xn--4pvxs.jp'),
            ('https://foô.com', 'xn--fo-9ja.com'),
        ]

    @override_switch('record-install-origins', active=True)
    def test_record_install_origins_error(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        parsed_data['install_origins'] = None  # Invalid
        with self.assertRaises(VersionCreateError):
            Version.from_upload(
                self.upload,
                self.addon,
                amo.RELEASE_CHANNEL_UNLISTED,
                selected_apps=[self.selected_app],
                parsed_data=parsed_data,
            )


class TestExtensionVersionFromUploadTransactional(TransactionTestCase, UploadMixin):
    filename = 'webextension_no_id.xpi'

    def setUp(self):
        super().setUp()
        # We can't use `setUpTestData` here because it doesn't play well with
        # the behavior of `TransactionTestCase`
        amo.tests.create_default_webext_appversion()

    @mock.patch('olympia.git.utils.create_git_extraction_entry')
    @override_switch('enable-uploads-commit-to-git-storage', active=False)
    def test_doesnt_create_git_extraction_entry_when_switch_is_off(
        self, create_entry_mock
    ):
        addon = addon_factory()
        user = user_factory(username='fancyuser')
        upload = self.get_upload('webextension_no_id.xpi', user=user)
        parsed_data = parse_addon(upload, addon, user=user)

        with transaction.atomic():
            version = Version.from_upload(
                upload,
                addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[amo.FIREFOX.id],
                parsed_data=parsed_data,
            )
        assert version.pk

        assert not create_entry_mock.called

    @mock.patch('olympia.git.utils.create_git_extraction_entry')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_creates_git_extraction_entry(self, create_entry_mock):
        addon = addon_factory()
        user = user_factory(username='fancyuser')
        upload = self.get_upload('webextension_no_id.xpi', user=user)
        parsed_data = parse_addon(upload, addon, user=user)

        with transaction.atomic():
            version = Version.from_upload(
                upload,
                addon,
                amo.RELEASE_CHANNEL_LISTED,
                selected_apps=[amo.FIREFOX.id],
                parsed_data=parsed_data,
            )
        assert version.pk

        create_entry_mock.assert_called_once_with(version=version)

    @mock.patch('olympia.git.utils.create_git_extraction_entry')
    @mock.patch('olympia.versions.models.utc_millesecs_from_epoch')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_does_not_create_git_extraction_entry_when_version_is_not_created(
        self, utc_millisecs_mock, create_entry_mock
    ):
        utc_millisecs_mock.side_effect = ValueError
        addon = addon_factory()
        user = user_factory(username='fancyuser')
        upload = self.get_upload('webextension_no_id.xpi', user=user)
        parsed_data = parse_addon(upload, addon, user=user)

        # Simulating an atomic transaction similar to what
        # create_version_for_upload does
        with pytest.raises(ValueError):
            with transaction.atomic():
                Version.from_upload(
                    upload,
                    addon,
                    amo.RELEASE_CHANNEL_LISTED,
                    selected_apps=[amo.FIREFOX.id],
                    parsed_data=parsed_data,
                )

        create_entry_mock.assert_not_called()


class TestStatusFromUpload(TestVersionFromUpload):
    filename = 'webextension.xpi'

    def setUp(self):
        super().setUp()
        self.current = self.addon.current_version

    def test_status(self):
        self.current.file.update(status=amo.STATUS_AWAITING_REVIEW)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert File.objects.filter(version=self.current)[0].status == (
            amo.STATUS_DISABLED
        )


class TestPermissionsFromUpload(TestVersionFromUpload):
    filename = 'webextension_all_perms.xpi'

    def setUp(self):
        super().setUp()
        self.addon.update(guid='allPermissions1@mozilla.com')
        self.current = self.addon.current_version

    def test_permissions_includes_devtools(self):
        parsed_data = parse_addon(self.upload, self.addon, user=self.fake_user)
        version = Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=parsed_data,
        )
        file = version.file

        permissions = file.permissions

        assert 'devtools' in permissions


class TestStaticThemeFromUpload(UploadMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.create(application=amo.FIREFOX.id, version=version)
            AppVersion.objects.create(application=amo.ANDROID.id, version=version)

    def setUp(self):
        path = 'src/olympia/devhub/tests/addons/static_theme.zip'
        self.user = user_factory()
        self.upload = self.get_upload(
            abspath=os.path.join(settings.ROOT, path), user=self.user
        )

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_while_nominated(self, generate_static_theme_preview_mock):
        self.addon = addon_factory(
            type=amo.ADDON_STATICTHEME,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        parsed_data = parse_addon(self.upload, self.addon, user=self.user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[],
            parsed_data=parsed_data,
        )
        assert generate_static_theme_preview_mock.call_count == 1

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_while_public(self, generate_static_theme_preview_mock):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        parsed_data = parse_addon(self.upload, self.addon, user=self.user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[],
            parsed_data=parsed_data,
        )
        assert generate_static_theme_preview_mock.call_count == 1

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_with_additional_backgrounds(
        self, generate_static_theme_preview_mock
    ):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        path = 'src/olympia/devhub/tests/addons/static_theme_tiled.zip'
        self.upload = self.get_upload(
            abspath=os.path.join(settings.ROOT, path), user=self.user
        )
        parsed_data = parse_addon(self.upload, self.addon, user=self.user)
        Version.from_upload(
            self.upload,
            self.addon,
            amo.RELEASE_CHANNEL_LISTED,
            selected_apps=[],
            parsed_data=parsed_data,
        )
        assert generate_static_theme_preview_mock.call_count == 1


class TestApplicationsVersions(TestCase):
    def setUp(self):
        super().setUp()
        self.version_kw = {'min_app_version': '5.0', 'max_app_version': '6.*'}

    def test_repr_when_compatible(self):
        addon = addon_factory(version_kw=self.version_kw)
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 and later'

    def test_repr_when_strict(self):
        addon = addon_factory(
            version_kw=self.version_kw, file_kw={'strict_compatibility': True}
        )
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 - 6.*'

    def test_repr_when_type_in_no_compat(self):
        # addon_factory() does not create ApplicationsVersions for types in
        # NO_COMPAT, so create an extension first and change the type
        # afterwards.
        addon = addon_factory(version_kw=self.version_kw)
        addon.update(type=amo.ADDON_DICT)
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 and later'

    def test_repr_when_low_app_support(self):
        addon = addon_factory(
            version_kw={'min_app_version': '3.0', 'max_app_version': '3.5'}
        )
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 3.0 - 3.5'

    def test_repr_when_unicode(self):
        addon = addon_factory(
            version_kw={'min_app_version': 'ك', 'max_app_version': 'ك'}
        )
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox ك - ك'


class TestVersionPreview(BasePreviewMixin, TestCase):
    def get_object(self):
        version_preview = VersionPreview.objects.create(
            version=addon_factory().current_version
        )
        return version_preview


class TestInstallOrigin(TestCase):
    def test_save_extract_base_domain(self):
        version = addon_factory().current_version
        install_origin = InstallOrigin.objects.create(
            version=version, origin='https://mozilla.github.io'
        )
        assert install_origin.base_domain == 'mozilla.github.io'

        install_origin.origin = 'https://foo.example.com'
        install_origin.save()
        assert install_origin.base_domain == 'example.com'
        install_origin.reload()
        assert install_origin.base_domain == 'example.com'

    def test_punycode(self):
        assert InstallOrigin.punycode('examplé.com') == 'xn--exampl-gva.com'
        assert InstallOrigin.punycode('xn--exampl-gva.com') == 'xn--exampl-gva.com'
        assert InstallOrigin.punycode('example.com') == 'example.com'


class TestDeniedInstallOrigin(TestCase):
    def test_save_always_punycode(self):
        denied_install_origin = DeniedInstallOrigin.objects.create(
            hostname_pattern='eXamplÉ.com'
        )
        assert denied_install_origin.hostname_pattern == 'xn--exampl-gva.com'

        denied_install_origin.hostname_pattern = '*.examplé.com'
        denied_install_origin.save()
        assert denied_install_origin.hostname_pattern == '*.xn--exampl-gva.com'
        denied_install_origin.reload()
        assert denied_install_origin.hostname_pattern == '*.xn--exampl-gva.com'

    def test_find_denied_origins_empty_list(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='foo.example.com')
        DeniedInstallOrigin.objects.create(
            hostname_pattern='bar.com', include_subdomains=True
        )
        assert DeniedInstallOrigin.find_denied_origins([]) == set()

    def test_find_denied_origins_nothing_denied(self):
        assert DeniedInstallOrigin.find_denied_origins(['https://example.com']) == set()
        assert (
            DeniedInstallOrigin.find_denied_origins(
                ['https://example.com', 'https://foo.bar.com']
            )
            == set()
        )
        assert (
            DeniedInstallOrigin.find_denied_origins(
                ['https://example.com', 'https://foo.baré.com']
            )
            == set()
        )

    def test_find_denied_origins_idn(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='examplé.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://foo.com', 'https://examplé.com']
        ) == {'https://examplé.com'}

    def test_find_denied_origins_with_port(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://foo.com', 'https://example.com:8888']
        ) == {'https://example.com:8888'}

    def test_find_denied_origins_multiple_matches(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'http://example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'http://example.com',
        }

    def test_find_denied_origins_glob(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.*')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'https://example.co.uk', 'https://foo.com']
        ) == {
            'https://example.com',
            'https://example.co.uk',
        }

    def test_find_denied_origins_multiple_denied_origins_match(self):
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        DeniedInstallOrigin.objects.create(hostname_pattern='example.*')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'http://example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'http://example.com',
        }

    def test_find_denied_origins_include_subdomains(self):
        DeniedInstallOrigin.objects.create(
            hostname_pattern='example.com', include_subdomains=True
        )
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'https://foo.example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'https://foo.example.com',
        }

    def test_find_denied_origins_include_subdomains_complex_match(self):
        DeniedInstallOrigin.objects.create(
            hostname_pattern='example.*', include_subdomains=True
        )
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'https://foo.example.com', 'https://foo.com']
        ) == {
            'https://example.com',
            'https://foo.example.com',
        }

    def test_find_denied_origins_input_not_an_origin(self):
        # The linter would raise an error, so we only need to ensure nothing
        # blows up on addons-server side.
        DeniedInstallOrigin.objects.create(hostname_pattern='example.com')
        assert DeniedInstallOrigin.find_denied_origins(
            ['https://example.com', 'rofl', 'https://foo.com']
        ) == {'https://example.com'}
