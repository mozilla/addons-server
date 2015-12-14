# -*- coding: utf-8 -*-
import hashlib
import os

from datetime import datetime

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.test.utils import override_settings

import mock
import pytest
from nose.tools import eq_
from pyquery import PyQuery

import amo
import amo.tests
from access import acl
from access.models import Group, GroupUser
from amo.helpers import user_media_url
from amo.tests import addon_factory
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import Addon, CompatOverride, CompatOverrideRange
from addons.tests.test_views import TestMobile
from applications.models import AppVersion
from devhub.models import ActivityLog
from editors.models import (ViewFullReviewQueue, ViewPendingQueue,
                            ViewPreliminaryQueue, ViewUnlistedFullReviewQueue,
                            ViewUnlistedPendingQueue,
                            ViewUnlistedPreliminaryQueue)
from files.models import File
from files.tests.test_models import UploadTest
from users.models import UserProfile
from versions import feeds, views
from versions.models import Version, ApplicationsVersions, source_upload_path
from versions.compare import (MAXVERSION, version_int, dict_from_int,
                              version_dict)


pytestmark = pytest.mark.django_db


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    eq_(version_int('3.5.0a1pre2'), 3050000001002)
    eq_(version_int(''), 200100)
    eq_(version_int('0'), 200100)
    eq_(version_int('*'), 99000000200100)
    eq_(version_int(MAXVERSION), MAXVERSION)
    eq_(version_int(MAXVERSION + 1), MAXVERSION)
    eq_(version_int('9999999'), MAXVERSION)


def test_version_int_compare():
    eq_(version_int('3.6.*'), version_int('3.6.99'))
    assert version_int('3.6.*') > version_int('3.6.8')


def test_version_asterix_compare():
    eq_(version_int('*'), version_int('99'))
    assert version_int('98.*') < version_int('*')
    eq_(version_int('5.*'), version_int('5.99'))
    assert version_int('5.*') > version_int('5.0.*')


def test_version_dict():
    eq_(version_dict('5.0'),
        {'major': 5,
         'minor1': 0,
         'minor2': None,
         'minor3': None,
         'alpha': None,
         'alpha_ver': None,
         'pre': None,
         'pre_ver': None})


def test_version_int_unicode():
    eq_(version_int(u'\u2322 ugh stephend'), 200100)


def test_dict_from_int():
    d = dict_from_int(3050000001002)
    eq_(d['major'], 3)
    eq_(d['minor1'], 5)
    eq_(d['minor2'], 0)
    eq_(d['minor3'], 0)
    eq_(d['alpha'], 'a')
    eq_(d['alpha_ver'], 1)
    eq_(d['pre'], 'pre')
    eq_(d['pre_ver'], 2)


@pytest.mark.parametrize("addon_type", amo.GROUP_TYPE_ADDON)
def test_watch_source(addon_type, mozilla_user):
    """watch_source flags addons as needing admin_review if there's source
    attached and the add-on is an extension."""
    # "mozilla_user" is a pytest fixture declared in the conftest.py file.
    # "addon_type" is a parameter from the "pytest.mark.parametrize" decorator:
    # This means this test will be run once for each addon_type in
    # amo.GROUP_TYPE_ADDON.
    addon = addon_factory(type=addon_type)
    version = addon.versions.get()
    version.update(source='some source file')
    # The add-on is admin flagged only if it needed the sources.
    is_extension = (addon_type == amo.ADDON_EXTENSION)
    assert addon.admin_review == is_extension


class TestVersion(amo.tests.TestCase):
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
        eq_(sorted(self.named_plat(self.version.compatible_platforms())),
            [u'android'])

    def test_mixed_version_supports_all_platforms(self):
        self.target_mobile()
        eq_(sorted(self.named_plat(self.version.compatible_platforms())),
            ['all', 'android', 'linux', 'mac', 'windows'])

    def test_non_mobile_version_supports_non_mobile_platforms(self):
        eq_(sorted(self.named_plat(self.version.compatible_platforms())),
            ['all', 'linux', 'mac', 'windows'])

    def test_major_minor(self):
        """Check that major/minor/alpha is getting set."""
        v = Version(version='3.0.12b2')
        eq_(v.major, 3)
        eq_(v.minor1, 0)
        eq_(v.minor2, 12)
        eq_(v.minor3, None)
        eq_(v.alpha, 'b')
        eq_(v.alpha_ver, 2)

        v = Version(version='3.6.1apre2+')
        eq_(v.major, 3)
        eq_(v.minor1, 6)
        eq_(v.minor2, 1)
        eq_(v.alpha, 'a')
        eq_(v.pre, 'pre')
        eq_(v.pre_ver, 2)

        v = Version(version='')
        eq_(v.major, None)
        eq_(v.minor1, None)
        eq_(v.minor2, None)
        eq_(v.minor3, None)

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
        assert self._get_version(amo.STATUS_UNREVIEWED).is_unreviewed
        assert self._get_version(amo.STATUS_PENDING).is_unreviewed
        assert not self._get_version(amo.STATUS_PUBLIC).is_unreviewed

    def test_version_delete(self):
        version = Version.objects.get(pk=81551)
        version.delete()

        addon = Addon.objects.no_cache().get(pk=3615)
        assert not Version.objects.filter(addon=addon).exists()
        assert not Version.unfiltered.filter(addon=addon).exists()

    def test_version_delete_files(self):
        version = Version.objects.get(pk=81551)
        eq_(version.files.count(), 1)
        version.delete()
        eq_(version.files.count(), 0)

    def test_version_delete_logs(self):
        user = UserProfile.objects.get(pk=55021)
        amo.set_user(user)
        # The transform don't know bout my users.
        version = Version.objects.get(pk=81551)
        eq_(ActivityLog.objects.count(), 0)
        version.delete()
        eq_(ActivityLog.objects.count(), 2)

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

    @mock.patch('files.models.File.hide_disabled_file')
    def test_new_version_disable_old_unreviewed(self, hide_mock):
        addon = Addon.objects.get(id=3615)
        # The status doesn't change for public files.
        qs = File.objects.filter(version=addon.current_version)
        eq_(qs.all()[0].status, amo.STATUS_PUBLIC)
        Version.objects.create(addon=addon)
        eq_(qs.all()[0].status, amo.STATUS_PUBLIC)
        assert not hide_mock.called

        qs.update(status=amo.STATUS_UNREVIEWED)
        version = Version.objects.create(addon=addon)
        version.disable_old_files()
        eq_(qs.all()[0].status, amo.STATUS_DISABLED)
        addon.current_version.all_files[0]
        assert hide_mock.called

    def test_new_version_beta(self):
        addon = Addon.objects.get(id=3615)
        qs = File.objects.filter(version=addon.current_version)
        qs.update(status=amo.STATUS_UNREVIEWED)

        version = Version.objects.create(addon=addon)
        File.objects.create(version=version, status=amo.STATUS_BETA)
        version.disable_old_files()
        eq_(qs.all()[0].status, amo.STATUS_UNREVIEWED)

    def test_version_int(self):
        version = Version.objects.get(pk=81551)
        version.save()
        eq_(version.version_int, 2017200200100)

    def test_large_version_int(self):
        # This version will fail to be written to the version_int
        # table because the resulting int is bigger than mysql bigint.
        version = Version.objects.get(pk=81551)
        version.version = '1237.2319.32161734.2383290.34'
        version.save()
        eq_(version.version_int, None)

    def test_version_update_info(self):
        addon = Addon.objects.get(pk=3615)
        r = self.client.get(reverse('addons.versions.update_info',
                                    args=(addon.slug, self.version.version)))
        eq_(r.status_code, 200)
        eq_(r['Content-Type'], 'application/xhtml+xml')
        eq_(PyQuery(r.content)('p').html(), 'Fix for an important bug')

        # Test update info in another language.
        with self.activate(locale='fr'):
            r = self.client.get(reverse('addons.versions.update_info',
                                        args=(addon.slug,
                                              self.version.version)))
            eq_(r.status_code, 200)
            eq_(r['Content-Type'], 'application/xhtml+xml')
            assert '<br/>' in r.content, (
                'Should be using XHTML self-closing tags!')
            eq_(PyQuery(r.content)('p').html(),
                u"Quelque chose en français.<br/><br/>Quelque chose d'autre.")

    def test_version_update_info_legacy_redirect(self):
        r = self.client.get('/versions/updateInfo/%s' % self.version.id,
                            follow=True)
        url = reverse('addons.versions.update_info',
                      args=(self.version.addon.slug, self.version.version))
        self.assert3xx(r, url, 301)

    def _reset_version(self, version):
        version.all_files[0].status = amo.STATUS_PUBLIC
        version.deleted = False

    def test_version_is_public(self):
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)

        # Base test. Everything is in order, the version should be public.
        eq_(version.is_public(), True)

        # Non-public file.
        self._reset_version(version)
        version.all_files[0].status = amo.STATUS_DISABLED
        eq_(version.is_public(), False)

        # Deleted version.
        self._reset_version(version)
        version.deleted = True
        eq_(version.is_public(), False)

        # Non-public addon.
        self._reset_version(version)
        with mock.patch('addons.models.Addon.is_public') as is_addon_public:
            is_addon_public.return_value = False
            eq_(version.is_public(), False)

    def test_is_compatible(self):
        # Base test for fixture before the rest.
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)
        eq_(version.is_compatible[0], True)
        eq_(version.is_compatible_app(amo.FIREFOX), True)

    def test_is_compatible_type(self):
        # Only ADDON_EXTENSIONs should be compatible.
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)
        addon.update(type=amo.ADDON_PERSONA)
        eq_(version.is_compatible[0], False)
        eq_(version.is_compatible_app(amo.FIREFOX), True)

    def test_is_compatible_strict_opt_in(self):
        # Add-ons opting into strict compatibility should not be compatible.
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)
        file = version.all_files[0]
        file.update(strict_compatibility=True)
        eq_(version.is_compatible[0], False)
        assert 'strict compatibility' in ''.join(version.is_compatible[1])
        eq_(version.is_compatible_app(amo.FIREFOX), True)

    def test_is_compatible_binary_components(self):
        # Add-ons using binary components should not be compatible.
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)
        file = version.all_files[0]
        file.update(binary_components=True)
        eq_(version.is_compatible[0], False)
        assert 'binary components' in ''.join(version.is_compatible[1])
        eq_(version.is_compatible_app(amo.FIREFOX), True)

    def test_is_compatible_app_max_version(self):
        # Add-ons with max app version < 4.0 should not be compatible.
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon, max_app_version='3.5')
        eq_(version.is_compatible_app(amo.FIREFOX), False)
        # An app that isn't supported should also be False.
        eq_(version.is_compatible_app(amo.THUNDERBIRD), False)
        # An app that can't do d2c should also be False.
        eq_(version.is_compatible_app(amo.UNKNOWN_APP), False)

    def test_compat_override_app_versions(self):
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)
        co = CompatOverride.objects.create(addon=addon)
        CompatOverrideRange.objects.create(compat=co, app=1, min_version='0',
                                           max_version=version.version,
                                           min_app_version='10.0a1',
                                           max_app_version='10.*')
        eq_(version.compat_override_app_versions(), [('10.0a1', '10.*')])

    def test_compat_override_app_versions_wildcard(self):
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon)
        co = CompatOverride.objects.create(addon=addon)
        CompatOverrideRange.objects.create(compat=co, app=1, min_version='0',
                                           max_version='*',
                                           min_app_version='10.0a1',
                                           max_app_version='10.*')
        eq_(version.compat_override_app_versions(), [('10.0a1', '10.*')])

    @mock.patch('addons.models.Addon.invalidate_d2c_versions')
    def test_invalidate_d2c_version_signals_on_delete(self, inv_mock):
        version = Addon.objects.get(pk=3615).current_version
        version.delete()
        assert inv_mock.called

    @mock.patch('addons.models.Addon.invalidate_d2c_versions')
    def test_invalidate_d2c_version_signals_on_save(self, inv_mock):
        addon = Addon.objects.get(pk=3615)
        amo.tests.version_factory(addon=addon)
        assert inv_mock.called

    def test_current_queue(self):
        queue_to_status = {
            ViewFullReviewQueue: [amo.STATUS_NOMINATED,
                                  amo.STATUS_LITE_AND_NOMINATED],
            ViewPendingQueue: [amo.STATUS_PUBLIC],
            ViewPreliminaryQueue: [amo.STATUS_LITE, amo.STATUS_UNREVIEWED]}
        unlisted_queue_to_status = {
            ViewUnlistedFullReviewQueue: [amo.STATUS_NOMINATED,
                                          amo.STATUS_LITE_AND_NOMINATED],
            ViewUnlistedPendingQueue: [amo.STATUS_PUBLIC],
            ViewUnlistedPreliminaryQueue: [amo.STATUS_LITE,
                                           amo.STATUS_UNREVIEWED]}

        for queue, statuses in queue_to_status.iteritems():  # Listed queues.
            for status in statuses:
                self.version.addon.update(status=status)
                assert self.version.current_queue == queue

        self.version.addon.update(is_listed=False)  # Unlisted queues.
        for queue, statuses in unlisted_queue_to_status.iteritems():
            for status in statuses:
                self.version.addon.update(status=status)
                assert self.version.current_queue == queue

    def test_get_url_path(self):
        eq_(self.version.get_url_path(),
            '/en-US/firefox/addon/a3615/versions/2.1.072')

    def test_unlisted_addon_get_url_path(self):
        self.version.addon.update(is_listed=False)
        eq_(self.version.get_url_path(), '')

    def test_source_upload_path(self):
        addon = Addon.objects.get(id=3615)
        version = amo.tests.version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'foo.tar.gz')
        assert uploaded_name.endswith(u'a3615-0.1-src.tar.gz')

    def test_source_upload_path_utf8_chars(self):
        addon = Addon.objects.get(id=3615)
        addon.update(slug=u'crosswarpex-확장')
        version = amo.tests.version_factory(addon=addon, version='0.1')
        uploaded_name = source_upload_path(version, 'crosswarpex-확장.tar.gz')
        assert uploaded_name.endswith(u'crosswarpex-확장-0.1-src.tar.gz')


@pytest.mark.parametrize("addon_status,file_status,is_unreviewed", [
    (amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED, True),
    (amo.STATUS_UNREVIEWED, amo.STATUS_LITE, True),
    (amo.STATUS_UNREVIEWED, amo.STATUS_LITE_AND_NOMINATED, True),
    (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_UNREVIEWED, amo.STATUS_PUBLIC, False),
    (amo.STATUS_UNREVIEWED, amo.STATUS_DISABLED, False),
    (amo.STATUS_UNREVIEWED, amo.STATUS_BETA, False),
    (amo.STATUS_LITE, amo.STATUS_UNREVIEWED, True),
    (amo.STATUS_LITE, amo.STATUS_LITE, False),
    (amo.STATUS_LITE, amo.STATUS_LITE_AND_NOMINATED, True),
    (amo.STATUS_LITE, amo.STATUS_NOMINATED, True),
    (amo.STATUS_LITE, amo.STATUS_PUBLIC, False),
    (amo.STATUS_LITE, amo.STATUS_DISABLED, False),
    (amo.STATUS_LITE, amo.STATUS_BETA, False),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_UNREVIEWED, True),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE, True),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE_AND_NOMINATED, True),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_PUBLIC, False),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_DISABLED, False),
    (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_BETA, False),
    (amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED, True),
    (amo.STATUS_NOMINATED, amo.STATUS_LITE, True),
    (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED, True),
    (amo.STATUS_NOMINATED, amo.STATUS_NOMINATED, True),
    (amo.STATUS_NOMINATED, amo.STATUS_PUBLIC, False),
    (amo.STATUS_NOMINATED, amo.STATUS_DISABLED, False),
    (amo.STATUS_NOMINATED, amo.STATUS_BETA, False),
    (amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED, True),
    (amo.STATUS_PUBLIC, amo.STATUS_LITE, False),
    (amo.STATUS_PUBLIC, amo.STATUS_LITE_AND_NOMINATED, True),
    (amo.STATUS_PUBLIC, amo.STATUS_NOMINATED, True),
    (amo.STATUS_PUBLIC, amo.STATUS_PUBLIC, False),
    (amo.STATUS_PUBLIC, amo.STATUS_DISABLED, False),
    (amo.STATUS_PUBLIC, amo.STATUS_BETA, False)])
def test_unreviewed_files(db, addon_status, file_status, is_unreviewed):
    """Files that need to be reviewed are returned by version.unreviewed_files.

    Use cases are triples taken from the "use_case" fixture above.
    """
    addon = amo.tests.addon_factory(status=addon_status, guid='foo')
    version = addon.latest_version
    file_ = version.files.get()
    file_.update(status=file_status)
    # If the addon is public, and we change its only file to something else
    # than public, it'll change to unreviewed.
    addon.update(status=addon_status)
    assert addon.reload().status == addon_status
    assert file_.reload().status == file_status


class TestViews(amo.tests.TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        super(TestViews, self).setUp()
        self.old_perpage = views.PER_PAGE
        views.PER_PAGE = 1
        self.addon = Addon.objects.get(id=11730)

    def tearDown(self):
        views.PER_PAGE = self.old_perpage
        super(TestViews, self).tearDown()

    def test_version_detail(self):
        base = '/en-US/firefox/addon/%s/versions/' % self.addon.slug
        urls = [(v.version, reverse('addons.versions',
                                    args=[self.addon.slug, v.version]))
                for v in self.addon.versions.all()]

        version, url = urls[0]
        r = self.client.get(url, follow=True)
        self.assert3xx(r, base + '?page=1#version-%s' % version)

        version, url = urls[1]
        r = self.client.get(url, follow=True)
        self.assert3xx(r, base + '?page=2#version-%s' % version)

    def test_version_detail_404(self):
        r = self.client.get(reverse('addons.versions',
                                    args=[self.addon.slug, 2]))
        eq_(r.status_code, 404)

    def get_content(self, beta=False):
        url = reverse('addons.beta-versions' if beta else 'addons.versions',
                      args=[self.addon.slug])
        return PyQuery(self.client.get(url).content)

    def test_version_source(self):
        self.addon.update(view_source=True)
        eq_(len(self.get_content()('a.source-code')), 1)

    def test_version_no_source_one(self):
        eq_(len(self.get_content()('a.source-code')), 0)

    def test_version_no_source_two(self):
        self.addon.update(view_source=True, status=amo.STATUS_NULL)
        eq_(len(self.get_content()('a.source-code')), 0)

    def test_version_link(self):
        addon = Addon.objects.get(id=11730)
        version = addon.current_version.version
        url = reverse('addons.versions', args=[addon.slug])
        doc = PyQuery(self.client.get(url).content)
        link = doc('.version h3 > a').attr('href')
        eq_(link, reverse('addons.versions', args=[addon.slug, version]))
        eq_(doc('.version').attr('id'), 'version-%s' % version)

    def test_beta_without_beta_builds(self):
        doc = self.get_content(beta=True)
        assert len(doc('.version')) == 0

    def test_beta_with_beta_builds(self):
        qs = File.objects.filter(version=self.addon.current_version)
        qs.update(status=amo.STATUS_BETA)
        doc = self.get_content(beta=True)
        version = self.addon.current_version.version
        assert doc('.version').attr('id') == 'version-%s' % version

    def test_version_list_for_unlisted_addon_returns_404(self):
        """Unlisted addons are not listed and have no version list."""
        self.addon.update(is_listed=False)
        url = reverse('addons.versions', args=[self.addon.slug])
        assert self.client.get(url).status_code == 404


class TestFeeds(amo.tests.TestCase):
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
        return PyQuery(r.content)

    def test_feed_elements_present(self):
        """specific elements are present and reasonably well formed"""
        doc = self.get_feed('a11730')
        eq_(doc('rss channel title')[0].text,
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
        assert item_pubdate.text == 'Thu, 21 May 2009 05:37:15 -0700'

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

        eq_(len(relations), len(page_relations))
        for rel, href in relations.iteritems():
            page = page_relations[rel]
            assert href.endswith('format:rss' if page == 1 else
                                 'format:rss?page=%s' % page)

    def test_feed_first_page(self):
        """first page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=1)
        eq_(doc('rss item title')[0].text,
            'Addon for DTC 1.3 - December  5, 2011')
        self.assert_page_relations(doc, {'self': 1, 'next': 2, 'last': 4})

    def test_feed_middle_page(self):
        """a middle page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=2)
        eq_(doc('rss item title')[0].text,
            'Addon for DTC 1.2 - December  5, 2011')
        self.assert_page_relations(doc, {'previous': 1, 'self': 2, 'next': 3,
                                         'last': 4})

    def test_feed_last_page(self):
        """last page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=4)
        eq_(doc('rss item title')[0].text,
            'Addon for DTC 1.0 - December  5, 2011')
        self.assert_page_relations(doc, {'previous': 3, 'self': 4, 'last': 4})

    def test_feed_invalid_page(self):
        """an invalid page falls back to page 1"""
        doc = self.get_feed('addon-337203', page=5)
        eq_(doc('rss item title')[0].text,
            'Addon for DTC 1.3 - December  5, 2011')

    def test_feed_no_page(self):
        """no page defaults to page 1"""
        doc = self.get_feed('addon-337203')
        eq_(doc('rss item title')[0].text,
            'Addon for DTC 1.3 - December  5, 2011')


class TestDownloadsBase(amo.tests.TestCase):
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
        eq_(response.status_code, 302)
        eq_(response.url,
            urlparams('%s%s/%s' % (host, self.addon.id, file_.filename),
                      filehash=file_.hash))
        eq_(response['X-Target-Digest'], file_.hash)

    def assert_served_internally(self, response):
        eq_(response.status_code, 200)
        eq_(response[settings.XSENDFILE_HEADER], self.file.guarded_file_path)

    def assert_served_locally(self, response, file_=None, attachment=False):
        host = settings.SITE_URL + user_media_url('addons')
        if attachment:
            host += '_attachments/'
        self.assert_served_by_host(response, host, file_)

    def assert_served_by_mirror(self, response, file_=None):
        url = settings.SITE_URL + user_media_url('addons')
        self.assert_served_by_host(response, url, file_)


class TestDownloadsUnlistedAddons(TestDownloadsBase):

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404
        assert self.client.get(self.latest_beta_url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.file_url).status_code == 302
        assert self.client.get(self.latest_url).status_code == 302
        assert self.client.get(self.latest_beta_url).status_code == 302

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.file_url).status_code == 404
        assert self.client.get(self.latest_url).status_code == 404
        assert self.client.get(self.latest_beta_url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.file_url).status_code == 302
        assert self.client.get(self.latest_url).status_code == 302
        assert self.client.get(self.latest_beta_url).status_code == 302


class TestDownloads(TestDownloadsBase):

    def test_file_404(self):
        r = self.client.get(reverse('downloads.file', args=[234]))
        eq_(r.status_code, 404)

    def test_public(self):
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        eq_(self.file.status, amo.STATUS_PUBLIC)
        self.assert_served_by_mirror(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_UNREVIEWED
        self.file.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_PENDING
        self.addon.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_type_attachment(self):
        self.assert_served_by_mirror(self.client.get(self.file_url))
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_nonbrowser_app(self):
        url = self.file_url.replace('firefox', 'thunderbird')
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = self.file_url + self.file.filename
        self.assert_served_by_mirror(self.client.get(url))

    def test_beta_file(self):
        url = reverse('downloads.file', args=[self.beta_file.id])
        self.assert_served_by_mirror(self.client.get(url),
                                     file_=self.beta_file)

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
        self.assert_served_locally(self.client.get(self.file_url))

    def test_public_addon_beta_file(self):
        self.file.update(status=amo.STATUS_BETA)
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.assert_served_by_mirror(self.client.get(self.file_url))

    def test_beta_addon_beta_file(self):
        self.addon.update(status=amo.STATUS_BETA)
        self.file.update(status=amo.STATUS_BETA)
        self.assert_served_locally(self.client.get(self.file_url))


class TestDisabledFileDownloads(TestDownloadsBase):

    def test_admin_disabled_404(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_user_disabled_404(self):
        self.addon.update(disabled_by_user=True)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_file_disabled_anon_404(self):
        self.file.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_file_disabled_unprivileged_404(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.file.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_editor(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(username='editor@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_admin(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(username='admin@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_author(self):
        # downloads_controller.php claims that add-on authors should be able to
        # download their disabled files.
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.client.login(username='admin@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_author(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_admin(self):
        self.addon.update(disabled_by_user=True)
        self.client.login(username='admin@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))


class TestUnlistedDisabledFileDownloads(TestDisabledFileDownloads):

    def setUp(self):
        super(TestDisabledFileDownloads, self).setUp()
        self.addon.update(is_listed=False)


class TestDownloadsLatest(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsLatest, self).setUp()
        self.platform = 5

    def assert_served_by_mirror(self, response):
        # Follow one more hop to hit the downloads.files view.
        r = self.client.get(response['Location'])
        super(TestDownloadsLatest, self).assert_served_by_mirror(r)

    def assert_served_locally(self, response, file_=None, attachment=False):
        # Follow one more hop to hit the downloads.files view.
        r = self.client.get(response.url)
        super(TestDownloadsLatest, self).assert_served_locally(
            r, file_, attachment)

    def test_404(self):
        url = reverse('downloads.latest', args=[123])
        eq_(self.client.get(url).status_code, 404)

    def test_type_none(self):
        r = self.client.get(self.latest_url)
        eq_(r.status_code, 302)
        url = self.file_url + '/' + self.file.filename
        assert r['Location'].endswith(url), r['Location']

    def test_success(self):
        assert self.addon.current_version
        self.assert_served_by_mirror(self.client.get(self.latest_url))

    def test_beta(self):
        response = self.client.get(self.latest_beta_url)
        assert response.status_code == 302
        beta_file_url = reverse('downloads.file', args=[self.beta_file.id])
        url = beta_file_url + '/' + self.beta_file.filename
        assert response['Location'].endswith(url)

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
        self.assert_served_by_mirror(self.client.get(url))

        # And now we match the platform in the url.
        self.file.platform = self.platform
        self.file.save()
        self.assert_served_by_mirror(self.client.get(url))

        # But we can't match platform=3.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        eq_(self.client.get(url).status_code, 404)

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

    def test_query_params(self):
        url = self.latest_url + '?src=xxx'
        r = self.client.get(url)
        eq_(r.status_code, 302)
        assert r['Location'].endswith('?src=xxx'), r['Location']


@override_settings(XSENDFILE=True)
class TestDownloadSource(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/admin']

    def setUp(self):
        super(TestDownloadSource, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        # Make sure non-ascii is ok.
        self.addon.update(slug=u'crosswarpex-확장')
        self.version = self.addon._latest_version
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
        self.client.login(username=self.user.email, password="password")
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
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
        eq_(response.status_code, 404)

    def test_group_binarysource_should_be_allowed(self):
        GroupUser.objects.create(user=self.user, group=self.group)
        self.client.login(username=self.user.email, password="password")
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
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
        eq_(response.status_code, 404)

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_returns_404(self):
        """File downloading isn't allowed for unlisted addons."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: True)
    def test_download_for_unlisted_addon_owner(self):
        """File downloading is allowed for addon owners."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.url).status_code == 200

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_reviewer(self):
        """File downloading isn't allowed for reviewers."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.url).status_code == 404

    @mock.patch.object(acl, 'check_addons_reviewer', lambda x: False)
    @mock.patch.object(acl, 'check_unlisted_addons_reviewer', lambda x: True)
    @mock.patch.object(acl, 'check_addon_ownership',
                       lambda *args, **kwargs: False)
    def test_download_for_unlisted_addon_unlisted_reviewer(self):
        """File downloading is allowed for unlisted reviewers."""
        self.addon.update(is_listed=False)
        assert self.client.get(self.url).status_code == 200


class TestVersionFromUpload(UploadTest, amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestVersionFromUpload, self).setUp()
        self.upload = self.get_upload(self.filename)
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(guid='guid@xpi')
        self.platform = amo.PLATFORM_MAC.id
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application=1, version=version)


class TestExtensionVersionFromUpload(TestVersionFromUpload):
    filename = 'extension.xpi'

    def test_carry_over_old_license(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        eq_(version.license_id, self.addon.current_version.license_id)

    def test_carry_over_license_no_version(self):
        self.addon.versions.all().delete()
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        eq_(version.license_id, None)

    def test_app_versions(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        assert amo.FIREFOX in version.compatible_apps
        app = version.compatible_apps[amo.FIREFOX]
        eq_(app.min.version, '3.0')
        eq_(app.max.version, '3.6.*')

    def test_version_number(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        eq_(version.version, '0.1')

    def test_file_platform(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        files = version.all_files
        eq_(len(files), 1)
        eq_(files[0].platform, self.platform)

    def test_file_name(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        files = version.all_files
        eq_(files[0].filename, u'delicious_bookmarks-0.1-fx-mac.xpi')

    def test_file_name_platform_all(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [amo.PLATFORM_ALL.id])
        files = version.all_files
        eq_(files[0].filename, u'delicious_bookmarks-0.1-fx.xpi')

    def test_android_creates_platform_files(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [amo.PLATFORM_ANDROID.id])
        files = version.all_files
        eq_(sorted(amo.PLATFORMS[f.platform].shortname for f in files),
            ['android'])

    def test_desktop_all_android_creates_all(self):
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.PLATFORM_ALL.id, amo.PLATFORM_ANDROID.id]
        )
        files = version.all_files
        eq_(sorted(amo.PLATFORMS[f.platform].shortname for f in files),
            ['all', 'android'])

    def test_android_with_mixed_desktop_creates_platform_files(self):
        version = Version.from_upload(
            self.upload,
            self.addon,
            [amo.PLATFORM_LINUX.id, amo.PLATFORM_ANDROID.id]
        )
        files = version.all_files
        eq_(sorted(amo.PLATFORMS[f.platform].shortname for f in files),
            ['android', 'linux'])

    def test_multiple_platforms(self):
        platforms = [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id]
        assert storage.exists(self.upload.path)
        with storage.open(self.upload.path) as file_:
            uploaded_hash = hashlib.md5(file_.read()).hexdigest()
        version = Version.from_upload(self.upload, self.addon, platforms)
        assert not storage.exists(self.upload.path), (
            "Expected original upload to move but it still exists.")
        files = version.all_files
        eq_(len(files), 2)
        eq_(sorted([f.platform for f in files]),
            sorted(platforms))
        eq_(sorted([f.filename for f in files]),
            [u'delicious_bookmarks-0.1-fx-%s.xpi' % (
                amo.PLATFORM_LINUX.shortname),
             u'delicious_bookmarks-0.1-fx-%s.xpi' % (
                 amo.PLATFORM_MAC.shortname)])
        for file_ in files:
            with storage.open(file_.file_path) as f:
                eq_(uploaded_hash,
                    hashlib.md5(f.read()).hexdigest(),
                    "md5 hash of %r does not match uploaded file" % (
                        file_.file_path))

    def test_file_multi_package(self):
        version = Version.from_upload(self.get_upload('multi-package.xpi'),
                                      self.addon,
                                      [self.platform])
        files = version.all_files
        assert files[0].is_multi_package

    def test_file_not_multi_package(self):
        version = Version.from_upload(self.upload, self.addon, [self.platform])
        files = version.all_files
        assert not files[0].is_multi_package


class TestSearchVersionFromUpload(TestVersionFromUpload):
    filename = 'search.xml'

    def setUp(self):
        super(TestSearchVersionFromUpload, self).setUp()
        self.addon.versions.all().delete()
        self.addon.update(type=amo.ADDON_SEARCH)
        self.now = datetime.now().strftime('%Y%m%d')

    def test_version_number(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        eq_(version.version, self.now)

    def test_file_name(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        files = version.all_files
        eq_(files[0].filename,
            u'delicious_bookmarks-%s.xml' % self.now)

    def test_file_platform_is_always_all(self):
        version = Version.from_upload(self.upload, self.addon,
                                      [self.platform])
        files = version.all_files
        eq_(len(files), 1)
        eq_(files[0].platform, amo.PLATFORM_ALL.id)


class TestStatusFromUpload(TestVersionFromUpload):
    filename = 'extension.xpi'

    def setUp(self):
        super(TestStatusFromUpload, self).setUp()
        self.current = self.addon.current_version

    def test_status(self):
        self.current.files.all().update(status=amo.STATUS_UNREVIEWED)
        Version.from_upload(self.upload, self.addon, [self.platform])
        eq_(File.objects.filter(version=self.current)[0].status,
            amo.STATUS_DISABLED)

    def test_status_beta(self):
        # Check that the add-on + files are in the public status.
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        eq_(File.objects.filter(version=self.current)[0].status,
            amo.STATUS_PUBLIC)
        # Create a new under review version with a pending file.
        upload = self.get_upload('extension-0.2.xpi')
        new_version = Version.from_upload(upload, self.addon, [self.platform])
        new_version.files.all()[0].update(status=amo.STATUS_PENDING)
        # Create a beta version.
        upload = self.get_upload('extension-0.2b1.xpi')
        beta_version = Version.from_upload(upload, self.addon, [self.platform],
                                           is_beta=True)
        # Check that it doesn't modify the public status.
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        eq_(File.objects.filter(version=self.current)[0].status,
            amo.STATUS_PUBLIC)
        # Check that the file created with the beta version is in beta status.
        eq_(File.objects.filter(version=beta_version)[0].status,
            amo.STATUS_BETA)
        # Check that the previously uploaded version is still pending.
        eq_(File.objects.filter(version=new_version)[0].status,
            amo.STATUS_PENDING)


class TestMobileVersions(TestMobile):

    def test_versions(self):
        r = self.client.get(reverse('addons.versions', args=['a3615']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'versions/mobile/version_list.html')


class TestApplicationsVersions(amo.tests.TestCase):

    def setUp(self):
        super(TestApplicationsVersions, self).setUp()
        self.version_kw = dict(min_app_version='5.0', max_app_version='6.*')

    def test_repr_when_compatible(self):
        addon = addon_factory(version_kw=self.version_kw)
        version = addon.current_version
        eq_(version.apps.all()[0].__unicode__(), 'Firefox 5.0 and later')

    def test_repr_when_strict(self):
        addon = addon_factory(version_kw=self.version_kw,
                              file_kw=dict(strict_compatibility=True))
        version = addon.current_version
        eq_(version.apps.all()[0].__unicode__(), 'Firefox 5.0 - 6.*')

    def test_repr_when_binary(self):
        addon = addon_factory(version_kw=self.version_kw,
                              file_kw=dict(binary_components=True))
        version = addon.current_version
        eq_(version.apps.all()[0].__unicode__(), 'Firefox 5.0 - 6.*')

    def test_repr_when_not_extension(self):
        addon = addon_factory(type=amo.ADDON_THEME,
                              version_kw=self.version_kw)
        version = addon.current_version
        eq_(version.apps.all()[0].__unicode__(), 'Firefox 5.0 - 6.*')

    def test_repr_when_low_app_support(self):
        addon = addon_factory(version_kw=dict(min_app_version='3.0',
                                              max_app_version='3.5'))
        version = addon.current_version
        eq_(version.apps.all()[0].__unicode__(), 'Firefox 3.0 - 3.5')

    def test_repr_when_unicode(self):
        addon = addon_factory(version_kw=dict(min_app_version=u'ك',
                                              max_app_version=u'ك'))
        version = addon.current_version
        eq_(unicode(version.apps.all()[0]), u'Firefox ك - ك')
