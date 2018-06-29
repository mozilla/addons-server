# -*- coding: utf-8 -*-
import hashlib
import os.path

from datetime import datetime, timedelta

from waffle.testutils import override_switch

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
import pytest

from pyquery import PyQuery

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon, AddonFeatureCompatibility, AddonReviewerFlags, CompatOverride,
    CompatOverrideRange)
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.applications.models import AppVersion
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.reviewers.models import (
    AutoApprovalSummary, ViewFullReviewQueue, ViewPendingQueue)
from olympia.users.models import UserProfile
from olympia.versions.models import (
    ApplicationsVersions, source_upload_path, Version, VersionPreview)


pytestmark = pytest.mark.django_db


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
        assert self._get_version(amo.STATUS_PENDING).is_unreviewed
        assert not self._get_version(amo.STATUS_PUBLIC).is_unreviewed

    @mock.patch('olympia.versions.tasks.VersionPreview.delete_preview_files')
    def test_version_delete(self, delete_preview_files_mock):
        version = Version.objects.get(pk=81551)
        version_preview = VersionPreview.objects.create(version=version)
        assert version.files.count() == 1
        version.delete()

        addon = Addon.objects.no_cache().get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert Version.unfiltered.filter(addon=addon).exists()
        assert version.files.count() == 1
        delete_preview_files_mock.assert_called_with(
            sender=None, instance=version_preview)

    def test_version_hard_delete(self):
        version = Version.objects.get(pk=81551)
        VersionPreview.objects.create(version=version)
        assert version.files.count() == 1
        version.delete(hard=True)

        addon = Addon.objects.no_cache().get(pk=3615)
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
        assert version.all_files[0].status == amo.STATUS_PUBLIC

        version.is_user_disabled = True
        version.all_files[0].reload()
        assert version.all_files[0].status == amo.STATUS_DISABLED
        assert version.all_files[0].original_status == amo.STATUS_PUBLIC

        version.is_user_disabled = False
        version.all_files[0].reload()
        assert version.all_files[0].status == amo.STATUS_PUBLIC
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

    def test_version_is_allowed_upload(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        # The transform don't know bout my deletions.
        version = Version.objects.get(pk=81551)
        assert version.is_allowed_upload()

    def test_version_is_not_allowed_upload(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        for platform in [amo.PLATFORM_LINUX.id,
                         amo.PLATFORM_WIN.id,
                         amo.PLATFORM_BSD.id]:
            file = File(platform=platform, version=version)
            file.save()
        version = Version.objects.get(pk=81551)
        assert version.is_allowed_upload()
        file = File(platform=amo.PLATFORM_MAC.id, version=version)
        file.save()
        # The transform don't know bout my new files.
        version = Version.objects.no_cache().get(pk=81551)
        assert not version.is_allowed_upload()

    def test_version_is_not_allowed_upload_full(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        for platform in [amo.PLATFORM_LINUX.id,
                         amo.PLATFORM_WIN.id,
                         amo.PLATFORM_MAC.id]:
            file = File(platform=platform, version=version)
            file.save()
        # The transform don't know bout my new files.
        version = Version.objects.get(pk=81551)
        assert not version.is_allowed_upload()

    def test_version_is_allowed_upload_search(self):
        version = Version.objects.get(pk=81551)
        version.addon.type = amo.ADDON_SEARCH
        version.addon.save()
        version.files.all()[0].delete()
        # The transform don't know bout my deletions.
        version = Version.objects.get(pk=81551)
        assert version.is_allowed_upload()

    def test_version_is_not_allowed_upload_search(self):
        version = Version.objects.get(pk=81551)
        version.addon.type = amo.ADDON_SEARCH
        version.addon.save()
        assert not version.is_allowed_upload()

    def test_version_is_allowed_upload_all(self):
        version = Version.objects.get(pk=81551)
        assert not version.is_allowed_upload()

    def test_version_is_not_allowed_upload_after_review(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        for platform in [amo.PLATFORM_LINUX.id,
                         amo.PLATFORM_WIN.id,
                         amo.PLATFORM_BSD.id]:
            file = File(platform=platform, version=version)
            file.save()
        version = Version.objects.get(pk=81551)
        assert version.is_allowed_upload()
        version.files.all()[0].update(status=amo.STATUS_PUBLIC)
        # The review has started so no more uploads now.
        version = Version.objects.get(pk=81551)
        assert not version.is_allowed_upload()

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_new_version_disable_old_unreviewed(self, hide_disabled_file_mock):
        addon = Addon.objects.get(id=3615)
        # The status doesn't change for public files.
        qs = File.objects.filter(version=addon.current_version)
        assert qs.all()[0].status == amo.STATUS_PUBLIC
        Version.objects.create(addon=addon)
        assert qs.all()[0].status == amo.STATUS_PUBLIC
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

    def test_version_update_info(self):
        addon = Addon.objects.get(pk=3615)
        response = self.client.get(
            reverse('addons.versions.update_info',
                    args=(addon.slug, self.version.version)))
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/xhtml+xml'
        # pyquery is annoying to use with XML and namespaces. Use the HTML
        # parser, but do check that xmlns attribute is present (required by
        # Firefox for the notes to be shown properly).
        doc = PyQuery(response.content, parser='html')
        assert doc('html').attr('xmlns') == 'http://www.w3.org/1999/xhtml'
        assert doc('p').html() == 'Fix for an important bug'

        # Test update info in another language.
        with self.activate(locale='fr'):
            response = self.client.get(
                reverse('addons.versions.update_info',
                        args=(addon.slug, self.version.version)))
            assert response.status_code == 200
            assert response['Content-Type'] == 'application/xhtml+xml'
            assert '<br/>' in response.content, (
                'Should be using XHTML self-closing tags!')
            doc = PyQuery(response.content, parser='html')
            assert doc('html').attr('xmlns') == 'http://www.w3.org/1999/xhtml'
            assert doc('p').html() == (
                u"Quelque chose en français.<br/><br/>Quelque chose d'autre.")

    def test_version_update_info_legacy_redirect(self):
        r = self.client.get('/versions/updateInfo/%s' % self.version.id,
                            follow=True)
        url = reverse('addons.versions.update_info',
                      args=(self.version.addon.slug, self.version.version))
        self.assert3xx(r, url, 301)

    def test_version_update_info_legacy_redirect_deleted(self):
        self.version.delete()
        response = self.client.get(
            '/en-US/firefox/versions/updateInfo/%s' % self.version.id)
        assert response.status_code == 404

    def test_version_update_info_no_unlisted(self):
        addon = Addon.objects.get(pk=3615)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        r = self.client.get(reverse('addons.versions.update_info',
                                    args=(addon.slug, self.version.version)))
        assert r.status_code == 404

    def _reset_version(self, version):
        version.all_files[0].status = amo.STATUS_PUBLIC
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
        addon.update(type=amo.ADDON_PERSONA)
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
        assert not version.is_compatible_app(amo.THUNDERBIRD)
        # An app that can't do d2c should also be False.
        assert not version.is_compatible_app(amo.UNKNOWN_APP)

    def test_compat_override_app_versions(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        co = CompatOverride.objects.create(addon=addon)
        CompatOverrideRange.objects.create(compat=co, app=1, min_version='0',
                                           max_version=version.version,
                                           min_app_version='10.0a1',
                                           max_app_version='10.*')
        assert version.compat_override_app_versions() == [('10.0a1', '10.*')]

    def test_compat_override_app_versions_wildcard(self):
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        co = CompatOverride.objects.create(addon=addon)
        CompatOverrideRange.objects.create(compat=co, app=1, min_version='0',
                                           max_version='*',
                                           min_app_version='10.0a1',
                                           max_app_version='10.*')
        assert version.compat_override_app_versions() == [('10.0a1', '10.*')]

    @mock.patch('olympia.addons.models.Addon.invalidate_d2c_versions')
    def test_invalidate_d2c_version_signals_on_delete(self, inv_mock):
        version = Addon.objects.get(pk=3615).current_version
        version.delete()
        assert inv_mock.called

    @mock.patch('olympia.addons.models.Addon.invalidate_d2c_versions')
    def test_invalidate_d2c_version_signals_on_save(self, inv_mock):
        addon = Addon.objects.get(pk=3615)
        version_factory(addon=addon)
        assert inv_mock.called

    def test_current_queue(self):
        queue_to_status = {
            ViewFullReviewQueue: amo.STATUS_NOMINATED,
            ViewPendingQueue: amo.STATUS_PUBLIC
        }

        for queue, status in queue_to_status.iteritems():  # Listed queues.
            self.version.addon.update(status=status)
            assert self.version.current_queue == queue

        self.make_addon_unlisted(self.version.addon)  # Unlisted: no queue.
        self.version.reload()
        assert self.version.current_queue is None

    def test_get_url_path(self):
        assert self.version.get_url_path() == (
            '/en-US/firefox/addon/a3615/versions/2.1.072')

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

        version.all_files = [
            File(status=amo.STATUS_AWAITING_REVIEW, is_webextension=False)]
        assert not version.is_ready_for_auto_approval

        version.all_files = [
            File(status=amo.STATUS_AWAITING_REVIEW, is_webextension=True)]
        version.channel = amo.RELEASE_CHANNEL_UNLISTED
        assert not version.is_ready_for_auto_approval

        version.channel = amo.RELEASE_CHANNEL_LISTED
        assert version.is_ready_for_auto_approval

        # With the auto-approval disabled flag set, it's still considered
        # "ready", even though the auto_approve code won't approve it.
        AddonReviewerFlags.objects.create(
            addon=addon, auto_approval_disabled=False)

        addon.type = amo.ADDON_THEME
        assert not version.is_ready_for_auto_approval

        addon.type = amo.ADDON_LPAPP
        assert version.is_ready_for_auto_approval

    def test_is_ready_for_auto_approval_addon_status(self):
        addon = Addon.objects.get(id=3615)
        addon.status = amo.STATUS_NOMINATED
        version = addon.current_version
        version.all_files = [
            File(status=amo.STATUS_AWAITING_REVIEW, is_webextension=True)]
        assert version.is_ready_for_auto_approval

        addon.status = amo.STATUS_DISABLED
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


@pytest.mark.parametrize("addon_status,file_status,is_unreviewed", [
    (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, True),
    (amo.STATUS_NOMINATED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_NOMINATED, amo.STATUS_PUBLIC, False),
    (amo.STATUS_NOMINATED, amo.STATUS_DISABLED, False),
    (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW, True),
    (amo.STATUS_PUBLIC, amo.STATUS_NOMINATED, True),
    (amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, False),
    (amo.STATUS_PUBLIC, amo.STATUS_DISABLED, False)])
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

    def setUp(self):
        super(TestVersionFromUpload, self).setUp()
        self.upload = self.get_upload(self.filename)
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(guid='guid@xpi')
        self.platform = amo.PLATFORM_MAC.id
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(
                application=amo.FIREFOX.id, version=version)
        self.dummy_parsed_data = {'version': '0.1'}


class TestExtensionVersionFromUpload(TestVersionFromUpload):
    filename = 'extension.xpi'

    def test_carry_over_old_license(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=self.dummy_parsed_data)
        assert version.license_id == self.addon.current_version.license_id

    def test_carry_over_license_no_version(self):
        self.addon.versions.all().delete()
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=self.dummy_parsed_data)
        assert version.license_id is None

    def test_app_versions(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
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
            self.upload, self.addon, [self.platform],
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
            version = Version.from_upload(self.upload, self.addon,
                                          [self.platform],
                                          amo.RELEASE_CHANNEL_LISTED,
                                          parsed_data=parsed_data)
        # Add an extra ApplicationsVersions. It should *not* appear in
        # version.compatible_apps, because that's a cached_property.
        new_app_vr_min = AppVersion.objects.create(
            application=amo.THUNDERBIRD.id, version='1.0')
        new_app_vr_max = AppVersion.objects.create(
            application=amo.THUNDERBIRD.id, version='2.0')
        ApplicationsVersions.objects.create(
            version=version, application=amo.THUNDERBIRD.id,
            min=new_app_vr_min, max=new_app_vr_max)
        assert amo.THUNDERBIRD not in version.compatible_apps
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '3.0'
        assert app.max.version == '3.6.*'

    def test_version_number(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        assert version.version == '0.1'

    def test_file_platform(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert len(files) == 1
        assert files[0].platform == self.platform

    def test_file_name(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert files[0].filename == u'delicious_bookmarks-0.1-fx-mac.xpi'

    def test_file_name_platform_all(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon,
                                      [amo.PLATFORM_ALL.id],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert files[0].filename == u'delicious_bookmarks-0.1-fx.xpi'

    def test_android_creates_platform_files(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon,
                                      [amo.PLATFORM_ANDROID.id],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['android'])

    def test_desktop_all_android_creates_all(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.PLATFORM_ALL.id, amo.PLATFORM_ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data,
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all', 'android'])

    def test_android_with_mixed_desktop_creates_platform_files(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.PLATFORM_LINUX.id, amo.PLATFORM_ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED,
            parsed_data=parsed_data,
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['android', 'linux'])

    def test_multiple_platforms(self):
        platforms = [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id]
        assert storage.exists(self.upload.path)
        with storage.open(self.upload.path) as file_:
            uploaded_hash = hashlib.sha256(file_.read()).hexdigest()
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, platforms,
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        assert not storage.exists(self.upload.path), (
            "Expected original upload to move but it still exists.")
        files = version.all_files
        assert len(files) == 2
        assert sorted([f.platform for f in files]) == (
            sorted(platforms))
        assert sorted([f.filename for f in files]) == (
            [u'delicious_bookmarks-0.1-fx-%s.xpi' % (
                amo.PLATFORM_LINUX.shortname),
             u'delicious_bookmarks-0.1-fx-%s.xpi' % (
                 amo.PLATFORM_MAC.shortname)])
        for file_ in files:
            with storage.open(file_.file_path) as f:
                assert uploaded_hash == hashlib.sha256(f.read()).hexdigest()

    def test_file_multi_package(self):
        self.upload = self.get_upload('multi-package.xpi')
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert files[0].is_multi_package

    def test_file_not_multi_package(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert not files[0].is_multi_package

    def test_track_upload_time(self):
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload.update(created=datetime.now() - timedelta(days=1))

        mock_timing_path = 'olympia.versions.models.statsd.timing'
        with mock.patch(mock_timing_path) as mock_timing:
            Version.from_upload(self.upload, self.addon, [self.platform],
                                amo.RELEASE_CHANNEL_LISTED,
                                parsed_data=self.dummy_parsed_data)

            upload_start = utc_millesecs_from_epoch(self.upload.created)
            now = utc_millesecs_from_epoch()
            rough_delta = now - upload_start
            actual_delta = mock_timing.call_args[0][1]

            fuzz = 2000  # 2 seconds
            assert (actual_delta >= (rough_delta - fuzz) and
                    actual_delta <= (rough_delta + fuzz))

    def test_new_version_is_10s_compatible_no_feature_compat_previously(self):
        assert not self.addon.feature_compatibility.pk
        self.upload = self.get_upload('multiprocess_compatible_extension.xpi')
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        assert version.pk
        assert self.addon.feature_compatibility.pk
        assert self.addon.feature_compatibility.e10s == amo.E10S_COMPATIBLE

    def test_new_version_is_10s_compatible(self):
        AddonFeatureCompatibility.objects.create(addon=self.addon)
        assert self.addon.feature_compatibility.e10s == amo.E10S_UNKNOWN
        self.upload = self.get_upload('multiprocess_compatible_extension.xpi')
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        assert version.pk
        assert self.addon.feature_compatibility.pk
        self.addon.feature_compatibility.reload()
        assert self.addon.feature_compatibility.e10s == amo.E10S_COMPATIBLE

    def test_new_version_is_webextension(self):
        self.addon.update(guid='@webextension-guid')
        AddonFeatureCompatibility.objects.create(addon=self.addon)
        assert self.addon.feature_compatibility.e10s == amo.E10S_UNKNOWN
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        assert version.pk
        assert self.addon.feature_compatibility.pk
        self.addon.feature_compatibility.reload()
        assert self.addon.feature_compatibility.e10s == (
            amo.E10S_COMPATIBLE_WEBEXTENSION)

    def test_nomination_inherited_for_updates(self):
        assert self.addon.status == amo.STATUS_PUBLIC
        self.addon.current_version.update(nomination=self.days_ago(2))
        pending_version = version_factory(
            addon=self.addon, nomination=self.days_ago(1), version='9.9',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        assert pending_version.nomination
        upload_version = Version.from_upload(
            self.upload, self.addon, [self.platform],
            amo.RELEASE_CHANNEL_LISTED, parsed_data=self.dummy_parsed_data)
        assert upload_version.nomination == pending_version.nomination


class TestSearchVersionFromUpload(TestVersionFromUpload):
    filename = 'search.xml'

    def setUp(self):
        super(TestSearchVersionFromUpload, self).setUp()
        self.addon.versions.all().delete()
        self.addon.update(type=amo.ADDON_SEARCH)
        self.now = datetime.now().strftime('%Y%m%d')

    def test_version_number(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        assert version.version == self.now

    def test_file_name(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED,
                                      parsed_data=parsed_data)
        files = version.all_files
        assert files[0].filename == (
            u'delicious_bookmarks-%s.xml' % self.now)

    def test_file_platform_is_always_all(self):
        parsed_data = parse_addon(self.upload, self.addon, user=mock.Mock())
        version = Version.from_upload(self.upload, self.addon, [self.platform],
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
        Version.from_upload(self.upload, self.addon, [self.platform],
                            amo.RELEASE_CHANNEL_LISTED,
                            parsed_data=self.dummy_parsed_data)
        assert File.objects.filter(version=self.current)[0].status == (
            amo.STATUS_DISABLED)


@override_switch('allow-static-theme-uploads', active=True)
class TestStaticThemeFromUpload(UploadTest):

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
        assert version.get_background_image_urls() == [
            '%s/%s/%s/%s' % (user_media_url('addons'), str(self.addon.id),
                             unicode(version.id), 'weta.png')
        ]

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
        assert version.get_background_image_urls() == [
            '%s/%s/%s/%s' % (user_media_url('addons'), str(self.addon.id),
                             unicode(version.id), 'weta.png')
        ]

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
        image_url_folder = u'%s/%s/%s/' % (
            user_media_url('addons'), self.addon.id, version.id)

        assert sorted(version.get_background_image_urls()) == [
            image_url_folder + 'empty.png',
            image_url_folder + 'transparent.gif',
            image_url_folder + 'weta_for_tiling.png',
        ]


class TestApplicationsVersions(TestCase):

    def setUp(self):
        super(TestApplicationsVersions, self).setUp()
        self.version_kw = dict(min_app_version='5.0', max_app_version='6.*')

    def test_repr_when_compatible(self):
        addon = addon_factory(version_kw=self.version_kw)
        version = addon.current_version
        assert version.apps.all()[0].__unicode__() == 'Firefox 5.0 and later'

    def test_repr_when_strict(self):
        addon = addon_factory(version_kw=self.version_kw,
                              file_kw=dict(strict_compatibility=True))
        version = addon.current_version
        assert version.apps.all()[0].__unicode__() == 'Firefox 5.0 - 6.*'

    def test_repr_when_binary(self):
        addon = addon_factory(version_kw=self.version_kw,
                              file_kw=dict(binary_components=True))
        version = addon.current_version
        assert version.apps.all()[0].__unicode__() == 'Firefox 5.0 - 6.*'

    def test_repr_when_type_in_no_compat(self):
        # addon_factory() does not create ApplicationsVersions for types in
        # NO_COMPAT, so create an extension first and change the type
        # afterwards.
        addon = addon_factory(version_kw=self.version_kw)
        addon.update(type=amo.ADDON_DICT)
        version = addon.current_version
        assert version.apps.all()[0].__unicode__() == 'Firefox 5.0 and later'

    def test_repr_when_low_app_support(self):
        addon = addon_factory(version_kw=dict(min_app_version='3.0',
                                              max_app_version='3.5'))
        version = addon.current_version
        assert version.apps.all()[0].__unicode__() == 'Firefox 3.0 - 3.5'

    def test_repr_when_unicode(self):
        addon = addon_factory(version_kw=dict(min_app_version=u'ك',
                                              max_app_version=u'ك'))
        version = addon.current_version
        assert unicode(version.apps.all()[0]) == u'Firefox ك - ك'


class TestVersionPreview(BasePreviewMixin, TestCase):
    def get_object(self):
        version_preview = VersionPreview.objects.create(
            version=addon_factory().current_version)
        return version_preview
