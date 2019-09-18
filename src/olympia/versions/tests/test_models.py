# -*- coding: utf-8 -*-
import hashlib
import os.path
import json

from datetime import datetime, timedelta

from django.db import transaction
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.test.testcases import TransactionTestCase

from unittest import mock
import pytest

from waffle.testutils import override_switch

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.applications.models import AppVersion
from olympia.constants.scanners import CUSTOMS
from olympia.files.models import File, FileUpload
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.lib.git import AddonGitRepository
from olympia.reviewers.models import AutoApprovalSummary
from olympia.users.models import UserProfile
from olympia.versions.compare import version_int
from olympia.versions.models import (
    ApplicationsVersions, Version, VersionPreview, source_upload_path)
from olympia.scanners.models import ScannersResult
from olympia.yara.models import YaraResult


pytestmark = pytest.mark.django_db


class TestVersionManager(TestCase):
    def test_latest_public_compatible_with(self):
        # Add compatible add-ons. We're going to request versions compatible
        # with 58.0.
        compatible_pack1 = addon_factory(
            name='Spanish Language Pack',
            type=amo.ADDON_LPAPP, target_locale='es',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        compatible_pack1.current_version.update(created=self.days_ago(2))
        compatible_version1 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        compatible_version1.update(created=self.days_ago(1))
        compatible_pack2 = addon_factory(
            name='French Language Pack',
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '58.0', 'max_app_version': '58.*'})
        compatible_version2 = compatible_pack2.current_version
        compatible_version2.update(created=self.days_ago(2))
        version_factory(
            addon=compatible_pack2, file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        # Add a more recent version for both add-ons, that would be compatible
        # with 58.0, but is not public/listed so should not be returned.
        version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        version_factory(
            addon=compatible_pack2,
            file_kw={'strict_compatibility': True,
                     'status': amo.STATUS_DISABLED},
            min_app_version='58.0', max_app_version='58.*')
        # And for the first pack, add a couple of versions that are also
        # compatible. They are older so should appear after.
        extra_compatible_version_1 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        extra_compatible_version_1.update(created=self.days_ago(3))
        extra_compatible_version_2 = version_factory(
            addon=compatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='58.0', max_app_version='58.*')
        extra_compatible_version_2.update(created=self.days_ago(4))

        # Add a few of incompatible add-ons.
        incompatible_pack1 = addon_factory(
            name='German Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP, target_locale='fr',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '56.0', 'max_app_version': '56.*'})
        version_factory(
            addon=incompatible_pack1, file_kw={'strict_compatibility': True},
            min_app_version='59.0', max_app_version='59.*')
        addon_factory(
            name='Italian Language Pack (incompatible with 58.0)',
            type=amo.ADDON_LPAPP, target_locale='it',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '59.0', 'max_app_version': '59.*'})
        # Even add a pack with a compatible version... not public. And another
        # one with a compatible version... not listed.
        incompatible_pack2 = addon_factory(
            name='Japanese Language Pack (public, but 58.0 version is not)',
            type=amo.ADDON_LPAPP, target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        version_factory(
            addon=incompatible_pack2,
            min_app_version='58.0', max_app_version='58.*',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'strict_compatibility': True})
        incompatible_pack3 = addon_factory(
            name='Nederlands Language Pack (58.0 version is unlisted)',
            type=amo.ADDON_LPAPP, target_locale='ja',
            file_kw={'strict_compatibility': True},
            version_kw={'min_app_version': '57.0', 'max_app_version': '57.*'})
        version_factory(
            addon=incompatible_pack3,
            min_app_version='58.0', max_app_version='58.*',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'strict_compatibility': True})

        appversions = {
            'min': version_int('58.0'),
            'max': version_int('58.0a'),
        }
        qs = Version.objects.latest_public_compatible_with(
            amo.FIREFOX.id, appversions)

        expected_versions = [
            compatible_version1, compatible_version2,
            extra_compatible_version_1, extra_compatible_version_2]
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
        super(TestVersion, self).setUp()
        self.version = Version.objects.get(pk=81551)

    def named_plat(self, ids):
        return [amo.PLATFORMS[i].shortname for i in ids]

    def target_mobile(self):
        app = amo.ANDROID.id
        app_vr = AppVersion.objects.create(application=app, version='1.0')
        ApplicationsVersions.objects.create(version=self.version,
                                            application=app,
                                            min=app_vr, max=app_vr)

    def test_compatible_apps(self):
        v = Version.objects.get(pk=81551)

        assert amo.FIREFOX in v.compatible_apps, "Missing Firefox >_<"

        # We should be re-using the same Version instance in
        # ApplicationsVersions loaded from <Version>._compat_map().
        assert id(v) == id(v.compatible_apps[amo.FIREFOX].version)

    def test_supported_platforms(self):
        v = Version.objects.get(pk=81551)
        assert amo.PLATFORM_ALL in v.supported_platforms

    def test_mobile_version_supports_only_mobile_platforms(self):
        self.version.apps.all().delete()
        self.target_mobile()
        assert (sorted(self.named_plat(self.version.compatible_platforms())) ==
                [u'android'])

    def test_mixed_version_supports_all_platforms(self):
        self.target_mobile()
        assert (sorted(self.named_plat(self.version.compatible_platforms())) ==
                ['all', 'android', 'linux', 'mac', 'windows'])

    def test_non_mobile_version_supports_non_mobile_platforms(self):
        assert (sorted(self.named_plat(self.version.compatible_platforms())) ==
                ['all', 'linux', 'mac', 'windows'])

    def test_major_minor(self):
        """Check that major/minor/alpha is getting set."""
        v = Version(version='3.0.12b2')
        assert v.major == 3
        assert v.minor1 == 0
        assert v.minor2 == 12
        assert v.minor3 is None
        assert v.alpha == 'b'
        assert v.alpha_ver == 2

        v = Version(version='3.6.1apre2+')
        assert v.major == 3
        assert v.minor1 == 6
        assert v.minor2 == 1
        assert v.alpha == 'a'
        assert v.pre == 'pre'
        assert v.pre_ver == 2

        v = Version(version='')
        assert v.major is None
        assert v.minor1 is None
        assert v.minor2 is None
        assert v.minor3 is None

    def test_is_restart_required(self):
        version = Version.objects.get(pk=81551)
        file_ = version.all_files[0]
        assert not file_.is_restart_required
        assert not version.is_restart_required

        file_.update(is_restart_required=True)
        version = Version.objects.get(pk=81551)
        assert version.is_restart_required

    def test_is_webextension(self):
        version = Version.objects.get(pk=81551)
        file_ = version.all_files[0]
        assert not file_.is_webextension
        assert not version.is_webextension

        file_.update(is_webextension=True)
        version = Version.objects.get(pk=81551)
        assert version.is_webextension

    def test_has_files(self):
        v = Version.objects.get(pk=81551)
        assert v.has_files, 'Version with files not recognized.'

        v.files.all().delete()
        v = Version.objects.get(pk=81551)
        assert not v.has_files, 'Version without files not recognized.'

    def _get_version(self, status):
        v = Version()
        v.all_files = [mock.Mock()]
        v.all_files[0].status = status
        return v

    def test_is_unreviewed(self):
        assert self._get_version(amo.STATUS_AWAITING_REVIEW).is_unreviewed
        assert not self._get_version(amo.STATUS_APPROVED).is_unreviewed

    @mock.patch('olympia.versions.tasks.VersionPreview.delete_preview_files')
    def test_version_delete(self, delete_preview_files_mock):
        version = Version.objects.get(pk=81551)
        version_preview = VersionPreview.objects.create(version=version)
        assert version.files.count() == 1
        version.delete()

        addon = Addon.objects.get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert Version.unfiltered.filter(addon=addon).exists()
        assert version.files.count() == 1
        delete_preview_files_mock.assert_called_with(
            sender=None, instance=version_preview)

    def test_version_delete_unlisted(self):
        version = Version.objects.get(pk=81551)
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.test_version_delete()

    def test_version_hard_delete(self):
        version = Version.objects.get(pk=81551)
        VersionPreview.objects.create(version=version)
        assert version.files.count() == 1
        version.delete(hard=True)

        addon = Addon.objects.get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert not Version.unfiltered.filter(addon=addon).exists()
        assert version.files.count() == 0
        assert not VersionPreview.objects.filter(version=version).exists()

    def test_version_delete_logs(self):
        user = UserProfile.objects.get(pk=55021)
        core.set_user(user)
        # The transform don't know bout my users.
        version = Version.objects.get(pk=81551)
        assert ActivityLog.objects.count() == 0
        version.delete()
        assert ActivityLog.objects.count() == 2

    def test_version_disable_and_reenable(self):
        version = Version.objects.get(pk=81551)
        assert version.all_files[0].status == amo.STATUS_APPROVED

        version.is_user_disabled = True
        version.all_files[0].reload()
        assert version.all_files[0].status == amo.STATUS_DISABLED
        assert version.all_files[0].original_status == amo.STATUS_APPROVED

        version.is_user_disabled = False
        version.all_files[0].reload()
        assert version.all_files[0].status == amo.STATUS_APPROVED
        assert version.all_files[0].original_status == amo.STATUS_NULL

    def test_version_disable_after_mozila_disabled(self):
        # Check that a user disable doesn't override mozilla disable
        version = Version.objects.get(pk=81551)
        version.all_files[0].update(status=amo.STATUS_DISABLED)

        version.is_user_disabled = True
        version.all_files[0].reload()
        assert version.all_files[0].status == amo.STATUS_DISABLED
        assert version.all_files[0].original_status == amo.STATUS_NULL

        version.is_user_disabled = False
        version.all_files[0].reload()
        assert version.all_files[0].status == amo.STATUS_DISABLED
        assert version.all_files[0].original_status == amo.STATUS_NULL

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
        version = Version.objects.create(addon=addon)
        version.disable_old_files()
        assert qs.all()[0].status == amo.STATUS_DISABLED
        addon.current_version.all_files[0]
        assert hide_disabled_file_mock.called

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_new_version_unlisted_dont_disable_old_unreviewed(
            self, hide_disabled_file_mock):
        addon = Addon.objects.get(id=3615)
        old_version = addon.current_version
        old_version.files.all().update(status=amo.STATUS_AWAITING_REVIEW)

        version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        version.disable_old_files()

        old_version.reload()
        assert old_version.files.all()[0].status == amo.STATUS_AWAITING_REVIEW
        assert not hide_disabled_file_mock.called

    def test_version_int(self):
        version = Version.objects.get(pk=81551)
        version.save()
        assert version.version_int == 2017200200100

    def test_large_version_int(self):
        # This version will fail to be written to the version_int
        # table because the resulting int is bigger than mysql bigint.
        version = Version.objects.get(pk=81551)
        version.version = '1237.2319.32161734.2383290.34'
        version.save()
        assert version.version_int is None

    def _reset_version(self, version):
        version.all_files[0].status = amo.STATUS_APPROVED
        version.deleted = False

    def test_version_is_public(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)

        # Base test. Everything is in order, the version should be public.
        assert version.is_public()

        # Non-public file.
        self._reset_version(version)
        version.all_files[0].status = amo.STATUS_DISABLED
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
        file = version.all_files[0]
        file.update(strict_compatibility=True)
        assert not version.is_compatible_by_default
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_by_default_binary_components(self):
        # Add-ons using binary components should not be compatible by default.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        file = version.all_files[0]
        file.update(binary_components=True)
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
        assert self.version.get_url_path() == (
            '/en-US/firefox/addon/a3615/versions/')

    def test_valid_versions(self):
        addon = Addon.objects.get(id=3615)
        additional_version = version_factory(
            addon=addon, version='0.1')
        amo.tests.file_factory(version=additional_version)
        version_factory(
            addon=addon, version='0.2',
            file_kw={'status': amo.STATUS_DISABLED})
        assert list(
            Version.objects.valid()) == [additional_version, self.version]

    def test_unlisted_addon_get_url_path(self):
        self.make_addon_unlisted(self.version.addon)
        self.version.reload()
        assert self.version.get_url_path() == ''

    def test_source_upload_path(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'foo.tar.gz')
        assert uploaded_name.endswith(u'a3615-0.1-src.tar.gz')

    def test_source_upload_path_utf8_chars(self):
        addon = Addon.objects.get(id=3615)
        addon.update(slug=u'crosswarpex-확장')
        version = version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'crosswarpex-확장.tar.gz')
        assert uploaded_name.endswith(u'crosswarpex-확장-0.1-src.tar.gz')

    def test_status_handles_invalid_status_id(self):
        version = Addon.objects.get(id=3615).current_version
        # When status is a valid one, one of STATUS_CHOICES_FILE return label.
        assert version.status == [
            amo.STATUS_CHOICES_FILE[version.all_files[0].status]]

        version.all_files[0].update(status=99)  # 99 isn't a valid status.
        # otherwise return the status code for reference.
        assert version.status == [u'[status:99]']

    def test_is_ready_for_auto_approval(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert not version.is_ready_for_auto_approval

        version.files.all().update(
            status=amo.STATUS_AWAITING_REVIEW, is_webextension=True)
        version.update(channel=amo.RELEASE_CHANNEL_LISTED)
        assert version.is_ready_for_auto_approval

        version.files.all().update(is_webextension=False)
        assert not version.is_ready_for_auto_approval

        version.files.all().update(is_webextension=True)
        assert version.is_ready_for_auto_approval

        # With the auto-approval disabled flag set, it's still considered
        # "ready", even though the auto_approve code won't approve it.
        AddonReviewerFlags.objects.create(
            addon=addon, auto_approval_disabled=False)
        assert version.is_ready_for_auto_approval

        addon.update(type=amo.ADDON_THEME)
        assert not version.is_ready_for_auto_approval

        addon.update(type=amo.ADDON_LPAPP)
        assert version.is_ready_for_auto_approval

        addon.update(type=amo.ADDON_DICT)
        assert version.is_ready_for_auto_approval

        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert not version.is_ready_for_auto_approval

    def test_is_ready_for_auto_approval_addon_status(self):
        addon = Addon.objects.get(id=3615)
        addon.status = amo.STATUS_NOMINATED
        version = addon.current_version
        version.files.all().update(
            status=amo.STATUS_AWAITING_REVIEW, is_webextension=True)
        assert version.is_ready_for_auto_approval

        addon.update(status=amo.STATUS_DISABLED)
        assert not version.is_ready_for_auto_approval

    def test_was_auto_approved(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        assert not version.was_auto_approved

        AutoApprovalSummary.objects.create(
            version=version, verdict=amo.AUTO_APPROVED)
        assert version.was_auto_approved

        version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        del version.all_files  # Reset all_files cache.
        assert not version.was_auto_approved

    @mock.patch('olympia.amo.tasks.sync_object_to_basket')
    def test_version_field_changes_not_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(
            approval_notes='Flôp', reviewed=self.days_ago(1),
            nomination=self.days_ago(2), version='1.42')
        assert sync_object_to_basket_mock.delay.call_count == 0

    @mock.patch('olympia.amo.tasks.sync_object_to_basket')
    def test_version_field_changes_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(recommendation_approved=True)
        assert sync_object_to_basket_mock.delay.call_count == 1
        sync_object_to_basket_mock.delay.assert_called_with('addon', addon.pk)

    @mock.patch('olympia.amo.tasks.sync_object_to_basket')
    def test_unlisted_version_deleted_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        sync_object_to_basket_mock.reset_mock()

        version.delete()
        assert sync_object_to_basket_mock.delay.call_count == 1
        sync_object_to_basket_mock.delay.assert_called_with('addon', addon.pk)

    @mock.patch('olympia.amo.tasks.sync_object_to_basket')
    def test_version_deleted_not_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        # We need to create a new version, if we delete current_version this
        # would be synced to basket because _current_version would change.
        new_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_NOMINATED})
        new_version.delete()
        assert sync_object_to_basket_mock.delay.call_count == 0


@pytest.mark.parametrize("addon_status,file_status,is_unreviewed", [
    (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, True),
    (amo.STATUS_NOMINATED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_NOMINATED, amo.STATUS_APPROVED, False),
    (amo.STATUS_NOMINATED, amo.STATUS_DISABLED, False),
    (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW, True),
    (amo.STATUS_APPROVED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_APPROVED, amo.STATUS_APPROVED, False),
    (amo.STATUS_APPROVED, amo.STATUS_DISABLED, False)])
def test_unreviewed_files(db, addon_status, file_status, is_unreviewed):
    """Files that need to be reviewed are returned by version.unreviewed_files.

    Use cases are triples taken from the "use_case" fixture above.
    """
    addon = amo.tests.addon_factory(status=addon_status, guid='foo')
    version = addon.current_version
    file_ = version.files.get()
    file_.update(status=file_status)
    # If the addon is public, and we change its only file to something else
    # than public, it'll change to unreviewed.
    addon.update(status=addon_status)
    assert addon.reload().status == addon_status
    assert file_.reload().status == file_status


class TestVersionFromUpload(UploadTest, TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    @classmethod
    def setUpTestData(cls):
        versions = {
            '3.0',
            '3.6.*',
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION
        }
        for version in versions:
            AppVersion.objects.create(application=amo.FIREFOX.id,
                                      version=version)
            AppVersion.objects.create(application=amo.ANDROID.id,
                                      version=version)

    def setUp(self):
        super(TestVersionFromUpload, self).setUp()
        self.upload = self.get_upload(self.filename)
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(guid='guid@xpi')
        self.selected_app = amo.FIREFOX.id
        self.dummy_parsed_data = {'version': '0.1'}


class TestExtensionVersionFromUpload(TestVersionFromUpload):
    filename = 'extension.xpi'

    def test_carry_over_old_license(self):
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.dummy_parsed_data)
        assert version.license_id == self.addon.current_version.license_id

    def test_mozilla_signed_extension(self):
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED, parsed_data=self.dummy_parsed_data)
        assert version.is_mozilla_signed
        assert version.approval_notes == (u'This version has been signed with '
                                          u'Mozilla internal certificate.')

    def test_carry_over_license_no_version(self):
        self.addon.versions.all().delete()
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.dummy_parsed_data)
        assert version.license_id is None

    def test_app_versions(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '3.0'
        assert app.max.version == '3.6.*'

    def test_duplicate_target_apps(self):
        # Note: the validator prevents this, but we also need to make sure
        # overriding failed validation is possible, so we need an extra check
        # in addons-server code.
        self.filename = 'duplicate_target_applications.xpi'
        self.addon.update(guid='duplicatetargetapps@xpi')
        self.upload = self.get_upload(self.filename)
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED, parsed_data=parsed_data)
        compatible_apps = version.compatible_apps
        assert len(compatible_apps) == 1
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '3.0'
        assert app.max.version == '3.6.*'

    def test_compatible_apps_is_pre_generated(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        # We mock File.from_upload() to prevent it from accessing
        # version.compatible_apps early - we want to test that the cache has
        # been generated regardless.
        with mock.patch('olympia.files.models.File.from_upload'):
            version = Version.from_upload(
                self.upload, self.addon, [self.selected_app],
                amo.RELEASE_CHANNEL_LISTED,
                parsed_data=parsed_data)
        # Add an extra ApplicationsVersions. It should *not* appear in
        # version.compatible_apps, because that's a cached_property.
        new_app_vr_min = AppVersion.objects.create(
            application=amo.ANDROID.id, version='1.0')
        new_app_vr_max = AppVersion.objects.create(
            application=amo.ANDROID.id, version='2.0')
        ApplicationsVersions.objects.create(
            version=version, application=amo.ANDROID.id,
            min=new_app_vr_min, max=new_app_vr_max)
        assert amo.ANDROID not in version.compatible_apps
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '3.0'
        assert app.max.version == '3.6.*'

    def test_version_number(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert version.version == '0.1'

    def test_file_platform(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        files = version.all_files
        assert len(files) == 1
        assert files[0].platform == amo.PLATFORM_ALL.id

    def test_file_name(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        files = version.all_files
        # Since https://github.com/mozilla/addons-server/issues/8752 we are
        # selecting PLATFORM_ALL every time as a temporary measure until
        # platforms get removed.
        assert files[0].filename == u'delicious_bookmarks-0.1-fx.xpi'

    def test_creates_platform_files(self):
        # We are creating files for 'all' platforms every time, #8752
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all'])

    def test_desktop_creates_all_platform_files(self):
        # We are creating files for 'all' platforms every time, #8752
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.FIREFOX.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data,
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all'])

    def test_android_creates_all_platform_files(self):
        # We are creating files for 'all' platforms every time, #8752
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data,
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all'])

    def test_platform_files_created(self):
        path = self.upload.path
        assert storage.exists(path)
        with storage.open(path) as file_:
            uploaded_hash = hashlib.sha256(file_.read()).hexdigest()
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [amo.FIREFOX.id, amo.ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert not storage.exists(path), (
            "Expected original upload to move but it still exists.")
        # set path to empty string (default db value) when deleted
        assert self.upload.path == ''
        files = version.all_files
        assert len(files) == 1
        assert sorted([f.platform for f in files]) == [amo.PLATFORM_ALL.id]
        assert sorted([f.filename for f in files]) == [
            u'delicious_bookmarks-0.1-fx.xpi'
        ]

        with storage.open(files[0].file_path) as f:
            assert uploaded_hash == hashlib.sha256(f.read()).hexdigest()

    def test_track_upload_time(self):
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload.update(created=datetime.now() - timedelta(days=1))

        mock_timing_path = 'olympia.versions.models.statsd.timing'
        with mock.patch(mock_timing_path) as mock_timing:
            Version.from_upload(
                self.upload, self.addon, [self.selected_app],
                amo.RELEASE_CHANNEL_LISTED,
                parsed_data=self.dummy_parsed_data)

            upload_start = utc_millesecs_from_epoch(self.upload.created)
            now = utc_millesecs_from_epoch()
            rough_delta = now - upload_start
            actual_delta = mock_timing.call_args[0][1]

            fuzz = 2000  # 2 seconds
            assert (actual_delta >= (rough_delta - fuzz) and
                    actual_delta <= (rough_delta + fuzz))

    def test_nomination_inherited_for_updates(self):
        assert self.addon.status == amo.STATUS_APPROVED
        self.addon.current_version.update(nomination=self.days_ago(2))
        pending_version = version_factory(
            addon=self.addon, nomination=self.days_ago(1), version='9.9',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        assert pending_version.nomination
        upload_version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED, parsed_data=self.dummy_parsed_data)
        assert upload_version.nomination == pending_version.nomination

    @mock.patch('olympia.amo.tasks.sync_object_to_basket')
    def test_from_upload_unlisted(self, sync_object_to_basket_mock):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.FIREFOX.id],
            amo.RELEASE_CHANNEL_UNLISTED,
            parsed_data=parsed_data,
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all'])
        # It's a new unlisted version, we should be syncing the add-on with
        # basket.
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', self.addon.pk)

    @mock.patch('olympia.amo.tasks.sync_object_to_basket')
    def test_from_upload_listed_not_synced_with_basket(
            self, sync_object_to_basket_mock):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.FIREFOX.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data,
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all'])
        # It's a new listed version, we should *not* be syncing the add-on with
        # basket through version_uploaded signal, but only when
        # _current_version changes, which isn't the case here.
        assert sync_object_to_basket_mock.delay.call_count == 0

    def test_set_version_to_scanners_result(self):
        scanners_result = ScannersResult.objects.create(
            upload=self.upload, scanner=CUSTOMS)
        assert scanners_result.version is None

        version = Version.from_upload(self.upload,
                                      self.addon,
                                      [self.selected_app],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=self.dummy_parsed_data)

        scanners_result.refresh_from_db()
        assert scanners_result.version == version

    def test_does_not_raise_when_scanners_result_does_not_exist(self):
        Version.from_upload(self.upload,
                            self.addon,
                            [self.selected_app],
                            amo.RELEASE_CHANNEL_LISTED,
                            parsed_data=self.dummy_parsed_data)

    def test_set_version_to_yara_result(self):
        yara_result = YaraResult.objects.create(upload=self.upload)
        assert yara_result.version is None

        version = Version.from_upload(self.upload, self.addon,
                                      [self.selected_app],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=self.dummy_parsed_data)

        yara_result.refresh_from_db()
        assert yara_result.version == version

    def test_does_not_raise_when_yara_result_does_not_exist(self):
        Version.from_upload(self.upload, self.addon,
                            [self.selected_app],
                            amo.RELEASE_CHANNEL_LISTED,
                            parsed_data=self.dummy_parsed_data)


class TestExtensionVersionFromUploadTransactional(
        TransactionTestCase, amo.tests.AMOPaths):
    filename = 'webextension_no_id.xpi'

    def setUp(self):
        super(TestExtensionVersionFromUploadTransactional, self).setUp()
        # We can't use `setUpTestData` here because it doesn't play well with
        # the behavior of `TransactionTestCase`
        amo.tests.create_default_webext_appversion()

        self.upload = self.get_upload(self.filename)
        self.addon = addon_factory()

    def get_upload(self, filename=None, abspath=None, validation=None,
                   addon=None, user=None, version=None, with_validation=True):
        fpath = self.file_fixture_path(filename)
        with open(abspath if abspath else fpath, 'rb') as fobj:
            xpi = fobj.read()
        upload = FileUpload.from_post(
            [xpi], filename=abspath or filename, size=1234)
        upload.addon = addon
        upload.user = user
        upload.version = version
        if with_validation:
            # Simulate what fetch_manifest() does after uploading an app.
            upload.validation = validation or json.dumps({
                'errors': 0, 'warnings': 1, 'notices': 2, 'metadata': {},
                'messages': []
            })
        upload.save()
        return upload

    @override_switch('enable-uploads-commit-to-git-storage', active=False)
    def test_doesnt_commit_to_git_by_default(self):
        addon = addon_factory()
        upload = self.get_upload('webextension_no_id.xpi')
        user = user_factory(username='fancyuser')
        parsed_data = parse_addon(upload, addon, user=user)

        with transaction.atomic():
            version = Version.from_upload(
                upload, addon, [amo.FIREFOX.id],
                amo.RELEASE_CHANNEL_LISTED,
                parsed_data=parsed_data)
        assert version.pk

        repo = AddonGitRepository(addon.pk)
        assert not os.path.exists(repo.git_repository_path)

    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_commits_to_git_waffle_enabled(self):
        addon = addon_factory()
        upload = self.get_upload('webextension_no_id.xpi')
        user = user_factory(username='fancyuser')
        parsed_data = parse_addon(upload, addon, user=user)

        with transaction.atomic():
            version = Version.from_upload(
                upload, addon, [amo.FIREFOX.id],
                amo.RELEASE_CHANNEL_LISTED,
                parsed_data=parsed_data)
        assert version.pk

        repo = AddonGitRepository(addon.pk)
        assert os.path.exists(repo.git_repository_path)

    @mock.patch('olympia.versions.tasks.extract_version_to_git.delay')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_commits_to_git_async(self, extract_mock):
        addon = addon_factory()
        upload = self.get_upload('webextension_no_id.xpi')
        upload.user = user_factory(username='fancyuser')
        parsed_data = parse_addon(upload, addon, user=upload.user)

        @transaction.atomic
        def create_new_version():
            return Version.from_upload(
                upload, addon, [amo.FIREFOX.id],
                amo.RELEASE_CHANNEL_LISTED,
                parsed_data=parsed_data)

        version = create_new_version()

        assert version.pk

        # Only once instead of twice
        extract_mock.assert_called_once_with(
            version_id=version.pk, author_id=upload.user.pk)

    @mock.patch('olympia.versions.tasks.extract_version_to_git.delay')
    @mock.patch('olympia.versions.models.utc_millesecs_from_epoch')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_commits_to_git_async_only_if_version_created(
            self, utc_millisecs_mock, extract_mock):
        utc_millisecs_mock.side_effect = ValueError
        addon = addon_factory()
        upload = self.get_upload('webextension_no_id.xpi')
        upload.user = user_factory(username='fancyuser')
        parsed_data = parse_addon(upload, addon, user=upload.user)

        # Simulating an atomic transaction similar to what
        # create_version_for_upload does
        with pytest.raises(ValueError):
            with transaction.atomic():
                Version.from_upload(
                    upload, addon, [amo.FIREFOX.id],
                    amo.RELEASE_CHANNEL_LISTED,
                    parsed_data=parsed_data)

        extract_mock.assert_not_called()


class TestSearchVersionFromUpload(TestVersionFromUpload):
    filename = 'search.xml'

    def setUp(self):
        super(TestSearchVersionFromUpload, self).setUp()
        self.addon.versions.all().delete()
        self.addon.update(type=amo.ADDON_SEARCH)
        self.now = datetime.now().strftime('%Y%m%d')

    def test_version_number(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert version.version == self.now

    def test_file_name(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        files = version.all_files
        assert files[0].filename == (
            u'delicious_bookmarks-%s.xml' % self.now)

    def test_file_platform_is_always_all(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        files = version.all_files
        assert len(files) == 1
        assert files[0].platform == amo.PLATFORM_ALL.id


class TestStatusFromUpload(TestVersionFromUpload):
    filename = 'extension.xpi'

    def setUp(self):
        super(TestStatusFromUpload, self).setUp()
        self.current = self.addon.current_version

    def test_status(self):
        self.current.files.all().update(status=amo.STATUS_AWAITING_REVIEW)
        Version.from_upload(
            self.upload, self.addon, [self.selected_app],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=self.dummy_parsed_data)
        assert File.objects.filter(version=self.current)[0].status == (
            amo.STATUS_DISABLED)


class TestStaticThemeFromUpload(UploadTest):

    @classmethod
    def setUpTestData(cls):
        versions = {
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
            amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION
        }
        for version in versions:
            AppVersion.objects.create(application=amo.FIREFOX.id,
                                      version=version)
            AppVersion.objects.create(application=amo.ANDROID.id,
                                      version=version)

    def setUp(self):
        path = 'src/olympia/devhub/tests/addons/static_theme.zip'
        self.upload = self.get_upload(
            abspath=os.path.join(settings.ROOT, path))

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_while_nominated(
            self, generate_static_theme_preview_mock):
        self.addon = addon_factory(
            type=amo.ADDON_STATICTHEME,
            status=amo.STATUS_NOMINATED,
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW
            }
        )
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [], amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert len(version.all_files) == 1
        assert generate_static_theme_preview_mock.call_count == 1

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_while_public(
            self, generate_static_theme_preview_mock):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [], amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert len(version.all_files) == 1
        assert generate_static_theme_preview_mock.call_count == 1

    @mock.patch('olympia.versions.models.generate_static_theme_preview')
    def test_new_version_with_additional_backgrounds(
            self, generate_static_theme_preview_mock):
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        path = 'src/olympia/devhub/tests/addons/static_theme_tiled.zip'
        self.upload = self.get_upload(
            abspath=os.path.join(settings.ROOT, path))
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload, self.addon, [], amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data)
        assert len(version.all_files) == 1
        assert generate_static_theme_preview_mock.call_count == 1


class TestApplicationsVersions(TestCase):

    def setUp(self):
        super(TestApplicationsVersions, self).setUp()
        self.version_kw = dict(min_app_version='5.0', max_app_version='6.*')

    def test_repr_when_compatible(self):
        addon = addon_factory(version_kw=self.version_kw)
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 and later'

    def test_repr_when_strict(self):
        addon = addon_factory(version_kw=self.version_kw,
                              file_kw=dict(strict_compatibility=True))
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 5.0 - 6.*'

    def test_repr_when_binary(self):
        addon = addon_factory(version_kw=self.version_kw,
                              file_kw=dict(binary_components=True))
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
        addon = addon_factory(version_kw=dict(min_app_version='3.0',
                                              max_app_version='3.5'))
        version = addon.current_version
        assert str(version.apps.all()[0]) == 'Firefox 3.0 - 3.5'

    def test_repr_when_unicode(self):
        addon = addon_factory(version_kw=dict(min_app_version=u'ك',
                                              max_app_version=u'ك'))
        version = addon.current_version
        assert str(version.apps.all()[0]) == u'Firefox ك - ك'


class TestVersionPreview(BasePreviewMixin, TestCase):
    def get_object(self):
        version_preview = VersionPreview.objects.create(
            version=addon_factory().current_version)
        return version_preview
