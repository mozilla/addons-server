# -*- coding: utf-8 -*-
import hashlib
import os

from datetime import datetime, timedelta

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.test.utils import override_settings

import mock
import pytest
from pyquery import PyQuery

from olympia import amo, core
from olympia.amo.tests import TestCase, version_factory
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.amo.helpers import user_media_url
from olympia.amo.tests import addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlencode, urlparams, utc_millesecs_from_epoch
from olympia.addons.models import (
    Addon, AddonFeatureCompatibility, CompatOverride, CompatOverrideRange)
from olympia.addons.tests.test_views import TestMobile
from olympia.applications.models import AppVersion
from olympia.editors.models import ViewFullReviewQueue, ViewPendingQueue
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.users.models import UserProfile
from olympia.versions import feeds, views
from olympia.versions.models import (
    Version, ApplicationsVersions, source_upload_path)
from olympia.versions.compare import (
    MAXVERSION, version_int, dict_from_int, version_dict)


pytestmark = pytest.mark.django_db


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    assert version_int('3.5.0a1pre2') == 3050000001002
    assert version_int('') == 200100
    assert version_int('0') == 200100
    assert version_int('*') == 99000000200100
    assert version_int(MAXVERSION) == MAXVERSION
    assert version_int(MAXVERSION + 1) == MAXVERSION
    assert version_int('9999999') == MAXVERSION


def test_version_int_compare():
    assert version_int('3.6.*') == version_int('3.6.99')
    assert version_int('3.6.*') > version_int('3.6.8')


def test_version_asterix_compare():
    assert version_int('*') == version_int('99')
    assert version_int('98.*') < version_int('*')
    assert version_int('5.*') == version_int('5.99')
    assert version_int('5.*') > version_int('5.0.*')


def test_version_dict():
    assert version_dict('5.0') == (
        {'major': 5,
         'minor1': 0,
         'minor2': None,
         'minor3': None,
         'alpha': None,
         'alpha_ver': None,
         'pre': None,
         'pre_ver': None})


def test_version_int_unicode():
    assert version_int(u'\u2322 ugh stephend') == 200100


def test_dict_from_int():
    d = dict_from_int(3050000001002)
    assert d['major'] == 3
    assert d['minor1'] == 5
    assert d['minor2'] == 0
    assert d['minor3'] == 0
    assert d['alpha'] == 'a'
    assert d['alpha_ver'] == 1
    assert d['pre'] == 'pre'
    assert d['pre_ver'] == 2


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

    def test_requires_restart(self):
        version = Version.objects.get(pk=81551)
        file_ = version.all_files[0]
        assert not file_.no_restart
        assert file_.requires_restart
        assert version.requires_restart

        file_.update(no_restart=True)
        version = Version.objects.get(pk=81551)
        assert not version.requires_restart

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

    def test_version_delete(self):
        version = Version.objects.get(pk=81551)
        version.delete()

        addon = Addon.objects.no_cache().get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert Version.unfiltered.filter(addon=addon).exists()

    def test_version_delete_files(self):
        version = Version.objects.get(pk=81551)
        assert version.files.count() == 1
        version.delete()
        assert version.files.count() == 1

    def test_version_hard_delete(self):
        version = Version.objects.get(pk=81551)
        version.delete(hard=True)

        addon = Addon.objects.no_cache().get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert not Version.unfiltered.filter(addon=addon).exists()

    def test_version_hard_delete_files(self):
        version = Version.objects.get(pk=81551)
        assert version.files.count() == 1
        version.delete(hard=True)
        assert version.files.count() == 0

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

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_new_version_beta_dont_disable_old_unreviewed(
            self, hide_disabled_file_mock):
        addon = Addon.objects.get(id=3615)
        qs = File.objects.filter(version=addon.current_version)
        qs.update(status=amo.STATUS_AWAITING_REVIEW)

        version = Version.objects.create(addon=addon)
        File.objects.create(version=version, status=amo.STATUS_BETA)
        version.disable_old_files()
        assert qs.all()[0].status == amo.STATUS_AWAITING_REVIEW
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

    def test_is_compatible(self):
        # Base test for fixture before the rest.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        assert version.is_compatible[0]
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_type(self):
        # Only ADDON_EXTENSIONs should be compatible.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        addon.update(type=amo.ADDON_PERSONA)
        assert not version.is_compatible[0]
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_strict_opt_in(self):
        # Add-ons opting into strict compatibility should not be compatible.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        file = version.all_files[0]
        file.update(strict_compatibility=True)
        assert not version.is_compatible[0]
        assert 'strict compatibility' in ''.join(version.is_compatible[1])
        assert version.is_compatible_app(amo.FIREFOX)

    def test_is_compatible_binary_components(self):
        # Add-ons using binary components should not be compatible.
        addon = Addon.objects.get(id=3615)
        version = version_factory(addon=addon)
        file = version.all_files[0]
        file.update(binary_components=True)
        assert not version.is_compatible[0]
        assert 'binary components' in ''.join(version.is_compatible[1])
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


@pytest.mark.parametrize("addon_status,file_status,is_unreviewed", [
    (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, True),
    (amo.STATUS_NOMINATED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_NOMINATED, amo.STATUS_PUBLIC, False),
    (amo.STATUS_NOMINATED, amo.STATUS_DISABLED, False),
    (amo.STATUS_NOMINATED, amo.STATUS_BETA, False),
    (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW, True),
    (amo.STATUS_PUBLIC, amo.STATUS_NOMINATED, True),
    (amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, False),
    (amo.STATUS_PUBLIC, amo.STATUS_DISABLED, False),
    (amo.STATUS_PUBLIC, amo.STATUS_BETA, False)])
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


class TestViews(TestCase):
    def setUp(self):
        super(TestViews, self).setUp()
        self.addon = addon_factory(
            slug=u'my-addôn', file_kw={'size': 1024},
            version_kw={'version': '1.0'})
        self.addon.current_version.update(created=self.days_ago(3))
        self.url_list = reverse('addons.versions', args=[self.addon.slug])
        self.url_list_betas = reverse(
            'addons.beta-versions', args=[self.addon.slug])
        self.url_detail = reverse(
            'addons.versions',
            args=[self.addon.slug, self.addon.current_version.version])

    @mock.patch.object(views, 'PER_PAGE', 1)
    def test_version_detail(self):
        version = version_factory(addon=self.addon, version='2.0')
        version.update(created=self.days_ago(2))
        version = version_factory(addon=self.addon, version='2.1b',
                                  file_kw={'status': amo.STATUS_BETA})
        version.update(created=self.days_ago(1))
        version_factory(addon=self.addon, version='2.2b',
                        file_kw={'status': amo.STATUS_BETA})
        urls = [(v.version, reverse('addons.versions',
                                    args=[self.addon.slug, v.version]))
                for v in self.addon.versions.all()]

        version, url = urls[0]
        assert version == '2.2b'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, self.url_list_betas + '?page=1#version-%s' % version)

        version, url = urls[1]
        assert version == '2.1b'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, self.url_list_betas + '?page=2#version-%s' % version)

        version, url = urls[2]
        assert version == '2.0'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, self.url_list + '?page=1#version-%s' % version)

        version, url = urls[3]
        assert version == '1.0'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, self.url_list + '?page=2#version-%s' % version)

    def test_version_detail_404(self):
        bad_pk = self.addon.current_version.pk + 42
        response = self.client.get(reverse('addons.versions',
                                           args=[self.addon.slug, bad_pk]))
        assert response.status_code == 404

    def get_content(self, beta=False):
        url = self.url_list_betas if beta else self.url_list
        response = self.client.get(url)
        assert response.status_code == 200
        return PyQuery(response.content)

    def test_version_source(self):
        self.addon.update(view_source=True)
        assert len(self.get_content()('a.source-code')) == 1

    def test_version_no_source_one(self):
        self.addon.update(view_source=False)
        assert len(self.get_content()('a.source-code')) == 0

    def test_version_addon_not_public(self):
        self.addon.update(view_source=True, status=amo.STATUS_NULL)
        response = self.client.get(self.url_list)
        assert response.status_code == 404

    def test_version_link(self):
        version = self.addon.current_version.version
        doc = self.get_content()
        link = doc('.version h3 > a').attr('href')
        assert link == self.url_detail
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_button_skips_contribution_roadblock(self):
        self.addon.update(
            wants_contributions=True, annoying=amo.CONTRIB_ROADBLOCK,
            paypal_id='foobar')
        version = version_factory(addon=self.addon, version='2.0')
        file_ = version.files.all()[0]
        doc = self.get_content()
        assert (doc('.button')[0].attrib['href'] ==
                file_.get_url_path(src='version-history'))

    def test_version_list_doesnt_show_unreviewed_versions_public_addon(self):
        version = self.addon.current_version.version
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version='2.1')
        doc = self.get_content()
        assert len(doc('.version')) == 1
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_does_show_unreviewed_versions_unreviewed_addon(self):
        version = self.addon.current_version.version
        file_ = self.addon.current_version.files.all()[0]
        file_.update(status=amo.STATUS_AWAITING_REVIEW)
        doc = self.get_content()
        assert len(doc('.version')) == 1
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_does_not_show_betas_by_default(self):
        version = self.addon.current_version.version
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_BETA},
            version='2.1b')
        doc = self.get_content()
        assert len(doc('.version')) == 1
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_beta_without_any_beta_version(self):
        doc = self.get_content(beta=True)
        assert len(doc('.version')) == 0

    def test_version_list_beta_shows_beta_version(self):
        version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_BETA},
            version='2.1b')
        doc = self.get_content(beta=True)
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_for_unlisted_addon_returns_404(self):
        """Unlisted addons are not listed and have no version list."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url_list).status_code == 404

    def test_version_detail_does_not_return_unlisted_versions(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url_detail)
        assert response.status_code == 404

    def test_version_list_file_size_uses_binary_prefix(self):
        response = self.client.get(self.url_list)
        assert '1.0 KiB' in response.content


class TestFeeds(TestCase):
    fixtures = ['addons/eula+contrib-addon', 'addons/default-to-compat']
    rel_ns = {'atom': 'http://www.w3.org/2005/Atom'}

    def setUp(self):
        super(TestFeeds, self).setUp()
        patcher = mock.patch.object(feeds, 'PER_PAGE', 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_feed(self, slug, **kwargs):
        beta = kwargs.pop('beta', False)
        url = reverse('addons.beta-versions.rss' if beta
                      else 'addons.versions.rss',
                      args=[slug])
        r = self.client.get(url, kwargs, follow=True)
        return PyQuery(r.content, parser='xml')

    def test_feed_elements_present(self):
        """specific elements are present and reasonably well formed"""
        doc = self.get_feed('a11730')
        assert doc('rss channel title')[0].text == (
            'IPv6 Google Search Version History')
        assert doc('rss channel link')[0].text.endswith('/en-US/firefox/')
        # assert <description> is present
        assert len(doc('rss channel description')[0].text) > 0
        # description doesn not contain the default object to string
        desc_elem = doc('rss channel description')[0]
        assert 'Content-Type:' not in desc_elem
        # title present
        assert len(doc('rss channel item title')[0].text) > 0
        # link present and well formed
        item_link = doc('rss channel item link')[0]
        assert item_link.text.endswith('/addon/a11730/versions/20090521')
        # guid present
        assert len(doc('rss channel item guid')[0].text) > 0
        # proper date format for item
        item_pubdate = doc('rss channel item pubDate')[0]
        assert item_pubdate.text == 'Thu, 21 May 2009 05:37:15 +0000'

    def test_status_beta_without_beta_builds(self):
        doc = self.get_feed('a11730', beta=True)
        assert len(doc('rss channel item link')) == 0

    def test_status_beta_with_beta_builds(self):
        addon = Addon.objects.get(id=11730)
        qs = File.objects.filter(version=addon.current_version)
        qs.update(status=amo.STATUS_BETA)

        doc = self.get_feed('a11730', beta=True)
        item_link = doc('rss channel item link')[0]
        assert item_link.text.endswith('/addon/a11730/versions/20090521')

    def assert_page_relations(self, doc, page_relations):
        rel = doc[0].xpath('//channel/atom:link', namespaces=self.rel_ns)
        relations = dict((link.get('rel'), link.get('href')) for link in rel)
        assert relations.pop('first').endswith('format:rss')

        assert len(relations) == len(page_relations)
        for rel, href in relations.iteritems():
            page = page_relations[rel]
            assert href.endswith('format:rss' if page == 1 else
                                 'format:rss?page=%s' % page)

    def test_feed_first_page(self):
        """first page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=1)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.3 - December  5, 2011')
        self.assert_page_relations(doc, {'self': 1, 'next': 2, 'last': 4})

    def test_feed_middle_page(self):
        """a middle page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=2)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.2 - December  5, 2011')
        self.assert_page_relations(doc, {'previous': 1, 'self': 2, 'next': 3,
                                         'last': 4})

    def test_feed_last_page(self):
        """last page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=4)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.0 - December  5, 2011')
        self.assert_page_relations(doc, {'previous': 3, 'self': 4, 'last': 4})

    def test_feed_invalid_page(self):
        """an invalid page falls back to page 1"""
        doc = self.get_feed('addon-337203', page=5)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.3 - December  5, 2011')

    def test_feed_no_page(self):
        """no page defaults to page 1"""
        doc = self.get_feed('addon-337203')
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.3 - December  5, 2011')


class TestDownloadsBase(TestCase):
    fixtures = ['base/addon_5299_gcal', 'base/users']

    def setUp(self):
        super(TestDownloadsBase, self).setUp()
        self.addon = Addon.objects.get(id=5299)
        self.file = File.objects.get(id=33046)
        self.beta_file = File.objects.get(id=64874)
        self.file_url = reverse('downloads.file', args=[self.file.id])
        self.latest_url = reverse('downloads.latest', args=[self.addon.slug])
        self.latest_beta_url = reverse('downloads.latest',
                                       kwargs={'addon_id': self.addon.slug,
                                               'beta': '-beta'})

    def assert_served_by_host(self, response, host, file_=None):
        if not file_:
            file_ = self.file
        assert response.status_code == 302
        assert response.url == (
            urlparams('%s%s/%s' % (host, self.addon.id, file_.filename),
                      filehash=file_.hash))
        assert response['X-Target-Digest'] == file_.hash

    def assert_served_internally(self, response, guarded=True):
        assert response.status_code == 200
        file_path = (self.file.guarded_file_path if guarded else
                     self.file.file_path)
        assert response[settings.XSENDFILE_HEADER] == file_path

    def assert_served_locally(self, response, file_=None, attachment=False):
        host = settings.SITE_URL + user_media_url('addons')
        if attachment:
            host += '_attachments/'
        self.assert_served_by_host(response, host, file_)

    def assert_served_by_cdn(self, response, file_=None):
        url = settings.SITE_URL + user_media_url('addons')
        self.assert_served_by_host(response, url, file_)


class TestDownloadsUnlistedVersions(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsUnlistedVersions, self).setUp()
        self.make_addon_unlisted(self.addon)
        # Remove the beta version or it's going to confuse things
        self.addon.versions.filter(files__status=amo.STATUS_BETA)[0].delete()

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.assert_served_internally(self.client.get(self.file_url), False)
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.assert_served_internally(self.client.get(self.file_url), False)
        assert self.client.get(self.latest_url).status_code == 404


class TestDownloads(TestDownloadsBase):

    def test_file_404(self):
        r = self.client.get(reverse('downloads.file', args=[234]))
        assert r.status_code == 404

    def test_public(self):
        assert self.addon.status == amo.STATUS_PUBLIC
        assert self.file.status == amo.STATUS_PUBLIC
        self.assert_served_by_cdn(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_AWAITING_REVIEW
        self.file.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_PENDING
        self.addon.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_type_attachment(self):
        self.assert_served_by_cdn(self.client.get(self.file_url))
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_nonbrowser_app(self):
        url = self.file_url.replace('firefox', 'thunderbird')
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = self.file_url + self.file.filename
        self.assert_served_by_cdn(self.client.get(url))

    def test_beta_file(self):
        url = reverse('downloads.file', args=[self.beta_file.id])
        self.assert_served_by_cdn(self.client.get(url),
                                  file_=self.beta_file)

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
        self.assert_served_locally(self.client.get(self.file_url))

    def test_public_addon_beta_file(self):
        self.file.update(status=amo.STATUS_BETA)
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.assert_served_by_cdn(self.client.get(self.file_url))

    def test_beta_addon_beta_file(self):
        self.addon.update(status=amo.STATUS_BETA)
        self.file.update(status=amo.STATUS_BETA)
        self.assert_served_locally(self.client.get(self.file_url))


class TestDisabledFileDownloads(TestDownloadsBase):

    def test_admin_disabled_404(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_user_disabled_404(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_anon_404(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_unprivileged_404(self):
        assert self.client.login(email='regular@mozilla.com')
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.get(self.file_url).status_code == 404

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_editor(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(email='editor@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_admin(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_author(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_author(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.login(email='g@gmail.com')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_admin(self):
        self.addon.update(disabled_by_user=True)
        self.client.login(email='admin@mozilla.com')
        self.assert_served_internally(self.client.get(self.file_url))


class TestUnlistedDisabledFileDownloads(TestDisabledFileDownloads):

    def setUp(self):
        super(TestDisabledFileDownloads, self).setUp()
        self.make_addon_unlisted(self.addon)
        self.grant_permission(
            UserProfile.objects.get(email='editor@mozilla.com'),
            'Addons:ReviewUnlisted')


class TestDownloadsLatest(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsLatest, self).setUp()
        self.platform = 5

    def test_404(self):
        url = reverse('downloads.latest', args=[123])
        assert self.client.get(url).status_code == 404

    def test_type_none(self):
        r = self.client.get(self.latest_url)
        assert r.status_code == 302
        url = '%s?%s' % (self.file.filename,
                         urlencode({'filehash': self.file.hash}))
        assert r['Location'].endswith(url), r['Location']

    def test_success(self):
        assert self.addon.current_version
        self.assert_served_by_cdn(self.client.get(self.latest_url))

    def test_beta(self):
        self.assert_served_by_cdn(self.client.get(self.latest_beta_url),
                                  file_=self.beta_file)

    def test_beta_unreviewed_addon(self):
        self.addon.status = amo.STATUS_PENDING
        self.addon.save()
        assert self.client.get(self.latest_beta_url).status_code == 404

    def test_beta_no_files(self):
        self.beta_file.update(status=amo.STATUS_PUBLIC)
        assert self.client.get(self.latest_beta_url).status_code == 404

    def test_platform(self):
        # We still match PLATFORM_ALL.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 5})
        self.assert_served_by_cdn(self.client.get(url))

        # And now we match the platform in the url.
        self.file.platform = self.platform
        self.file.save()
        self.assert_served_by_cdn(self.client.get(url))

        # But we can't match platform=3.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        assert self.client.get(url).status_code == 404

    def test_type(self):
        url = reverse('downloads.latest', kwargs={'addon_id': self.addon.slug,
                                                  'type': 'attachment'})
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_and_type(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 5,
                              'type': 'attachment'})
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 5,
                              'type': 'attachment'})
        url += self.file.filename
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_multiple_objects(self):
        f = File.objects.create(platform=3, version=self.file.version,
                                filename='unst.xpi', status=self.file.status)
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        self.assert_served_locally(self.client.get(url), file_=f)


@override_settings(XSENDFILE=True)
class TestDownloadSource(TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super(TestDownloadSource, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        # Make sure non-ascii is ok.
        self.addon.update(slug=u'crosswarpex-확장')
        self.version = self.addon.current_version
        tdir = temp.gettempdir()
        self.source_file = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        self.source_file.write('a' * (2 ** 21))
        self.source_file.seek(0)
        self.version.source = DjangoFile(self.source_file)
        self.version.save()
        self.filename = os.path.basename(self.version.source.path)
        self.user = UserProfile.objects.get(email="del@icio.us")
        self.group = Group.objects.create(
            name='Editors BinarySource',
            rules='Editors:BinarySource'
        )
        self.url = reverse('downloads.source', args=(self.version.pk, ))

    def test_owner_should_be_allowed(self):
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER]
        assert 'Content-Disposition' in response
        filename = self.filename
        if not isinstance(filename, unicode):
            filename = filename.decode('utf8')
        assert filename in response['Content-Disposition'].decode('utf8')
        path = self.version.source.path
        if not isinstance(path, unicode):
            path = path.decode('utf8')
        assert response[settings.XSENDFILE_HEADER].decode('utf8') == path

    def test_anonymous_should_not_be_allowed(self):
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version(self):
        self.version.delete()
        GroupUser.objects.create(user=self.user, group=self.group)
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_group_binarysource_should_be_allowed(self):
        GroupUser.objects.create(user=self.user, group=self.group)
        self.client.login(email=self.user.email)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER]
        assert 'Content-Disposition' in response
        filename = self.filename
        if not isinstance(filename, unicode):
            filename = filename.decode('utf8')
        assert filename in response['Content-Disposition'].decode('utf8')
        path = self.version.source.path
        if not isinstance(path, unicode):
            path = path.decode('utf8')
        assert response[settings.XSENDFILE_HEADER].decode('utf8') == path

    def test_no_source_should_go_in_404(self):
        self.version.source = None
        self.version.save()
        response = self.client.get(self.url)
        assert response.status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200


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


class TestExtensionVersionFromUpload(TestVersionFromUpload):
    filename = 'extension.xpi'

    def test_carry_over_old_license(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert version.license_id == self.addon.current_version.license_id

    def test_carry_over_license_no_version(self):
        self.addon.versions.all().delete()
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert version.license_id is None

    def test_app_versions(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        assert app.min.version == '3.0'
        assert app.max.version == '3.6.*'

    def test_compatible_apps_is_pre_generated(self):
        # We mock File.from_upload() to prevent it from accessing
        # version.compatible_apps early - we want to test that the cache has
        # been generated regardless.
        with mock.patch('olympia.files.models.File.from_upload'):
            version = Version.from_upload(self.upload, self.addon,
                                          [self.platform],
                                          amo.RELEASE_CHANNEL_LISTED)
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
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert version.version == '0.1'

    def test_file_platform(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert len(files) == 1
        assert files[0].platform == self.platform

    def test_file_name(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert files[0].filename == u'delicious_bookmarks-0.1-fx-mac.xpi'

    def test_file_name_platform_all(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [amo.PLATFORM_ALL.id],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert files[0].filename == u'delicious_bookmarks-0.1-fx.xpi'

    def test_android_creates_platform_files(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [amo.PLATFORM_ANDROID.id],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['android'])

    def test_desktop_all_android_creates_all(self):
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.PLATFORM_ALL.id, amo.PLATFORM_ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['all', 'android'])

    def test_android_with_mixed_desktop_creates_platform_files(self):
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.PLATFORM_LINUX.id, amo.PLATFORM_ANDROID.id],
            amo.RELEASE_CHANNEL_LISTED
        )
        files = version.all_files
        assert sorted(amo.PLATFORMS[f.platform].shortname for f in files) == (
            ['android', 'linux'])

    def test_multiple_platforms(self):
        platforms = [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id]
        assert storage.exists(self.upload.path)
        with storage.open(self.upload.path) as file_:
            uploaded_hash = hashlib.sha256(file_.read()).hexdigest()
        version = Version.from_upload(self.upload, self.addon, platforms,
                                      amo.RELEASE_CHANNEL_LISTED)
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
        version = Version.from_upload(self.get_upload('multi-package.xpi'),
                                      self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert files[0].is_multi_package

    def test_file_not_multi_package(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert not files[0].is_multi_package

    def test_track_upload_time(self):
        # Set created time back (just for sanity) otherwise the delta
        # would be in the microsecond range.
        self.upload.update(created=datetime.now() - timedelta(days=1))

        mock_timing_path = 'olympia.versions.models.statsd.timing'
        with mock.patch(mock_timing_path) as mock_timing:
            Version.from_upload(self.upload, self.addon, [self.platform],
                                amo.RELEASE_CHANNEL_LISTED)

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
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert version.pk
        assert self.addon.feature_compatibility.pk
        assert self.addon.feature_compatibility.e10s == amo.E10S_COMPATIBLE

    def test_new_version_is_10s_compatible(self):
        AddonFeatureCompatibility.objects.create(addon=self.addon)
        assert self.addon.feature_compatibility.e10s == amo.E10S_UNKNOWN
        self.upload = self.get_upload('multiprocess_compatible_extension.xpi')
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert version.pk
        assert self.addon.feature_compatibility.pk
        self.addon.feature_compatibility.reload()
        assert self.addon.feature_compatibility.e10s == amo.E10S_COMPATIBLE

    def test_new_version_is_webextension(self):
        self.addon.update(guid='@webextension-guid')
        AddonFeatureCompatibility.objects.create(addon=self.addon)
        assert self.addon.feature_compatibility.e10s == amo.E10S_UNKNOWN
        self.upload = self.get_upload('webextension.xpi')
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
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
            amo.RELEASE_CHANNEL_LISTED)
        assert upload_version.nomination == pending_version.nomination


class TestSearchVersionFromUpload(TestVersionFromUpload):
    filename = 'search.xml'

    def setUp(self):
        super(TestSearchVersionFromUpload, self).setUp()
        self.addon.versions.all().delete()
        self.addon.update(type=amo.ADDON_SEARCH)
        self.now = datetime.now().strftime('%Y%m%d')

    def test_version_number(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        assert version.version == self.now

    def test_file_name(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
        files = version.all_files
        assert files[0].filename == (
            u'delicious_bookmarks-%s.xml' % self.now)

    def test_file_platform_is_always_all(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform],
                                      amo.RELEASE_CHANNEL_LISTED)
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
                            amo.RELEASE_CHANNEL_LISTED)
        assert File.objects.filter(version=self.current)[0].status == (
            amo.STATUS_DISABLED)

    def test_status_beta(self):
        # Check that the add-on + files are in the public status.
        assert self.addon.status == amo.STATUS_PUBLIC
        assert File.objects.filter(version=self.current)[0].status == (
            amo.STATUS_PUBLIC)
        # Create a new under review version with a pending file.
        upload = self.get_upload('extension-0.2.xpi')
        new_version = Version.from_upload(upload, self.addon, [self.platform],
                                          amo.RELEASE_CHANNEL_LISTED)
        new_version.files.all()[0].update(status=amo.STATUS_PENDING)
        # Create a beta version.
        upload = self.get_upload('extension-0.2b1.xpi')
        beta_version = Version.from_upload(upload, self.addon, [self.platform],
                                           amo.RELEASE_CHANNEL_LISTED,
                                           is_beta=True)
        # Check that it doesn't modify the public status.
        assert self.addon.status == amo.STATUS_PUBLIC
        assert File.objects.filter(version=self.current)[0].status == (
            amo.STATUS_PUBLIC)
        # Check that the file created with the beta version is in beta status.
        assert File.objects.filter(version=beta_version)[0].status == (
            amo.STATUS_BETA)
        # Check that the previously uploaded version is still pending.
        assert File.objects.filter(version=new_version)[0].status == (
            amo.STATUS_PENDING)


class TestMobileVersions(TestMobile):

    def test_versions(self):
        r = self.client.get(reverse('addons.versions', args=['a3615']))
        assert r.status_code == 200
        self.assertTemplateUsed(r, 'versions/mobile/version_list.html')


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

    def test_repr_when_not_extension(self):
        addon = addon_factory(type=amo.ADDON_THEME,
                              version_kw=self.version_kw)
        version = addon.current_version
        assert version.apps.all()[0].__unicode__() == 'Firefox 5.0 - 6.*'

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
