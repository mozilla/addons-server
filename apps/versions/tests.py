import hashlib
import os

from datetime import datetime, timedelta
from django.conf import settings

import mock
import test_utils
from nose.tools import eq_
from pyquery import PyQuery

import amo
import files.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from addons.tests.test_views import TestMobile
from applications.models import AppVersion
from devhub.models import ActivityLog
from files.models import File, Platform
from users.models import UserProfile
from versions import views
from versions.models import Version
from versions.compare import version_int, dict_from_int


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    eq_(version_int("3.5.0a1pre2"), 3050000001002)
    eq_(version_int(""), 200100)


def test_version_int_compare():
    eq_(version_int('3.6.*'), version_int('3.6.99'))
    assert version_int('3.6.*') > version_int('3.6.8')


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


class TestVersion(test_utils.TestCase):
    fixtures = ['base/addon_3615', 'base/admin', 'base/platforms']

    def test_compatible_apps(self):
        v = Version.objects.get(pk=81551)

        assert amo.FIREFOX in v.compatible_apps, "Missing Firefox >_<"

    def test_supported_platforms(self):
        v = Version.objects.get(pk=81551)
        assert amo.PLATFORM_ALL in v.supported_platforms

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
        assert Addon.uncached.get(pk=3615)

    def test_version_delete_files(self):
        version = Version.objects.get(pk=81551)
        eq_(version.files.count(), 1)
        version.delete()
        eq_(version.files.count(), 0)

    def test_version_delete_logs(self):
        user = UserProfile.objects.get(pk=55021)
        amo.set_user(user)
        version = Version.objects.get(pk=81551)
        eq_(ActivityLog.objects.count(), 0)
        version.delete()
        eq_(ActivityLog.objects.count(), 2)

    def test_version_is_allowed_upload(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        assert version.is_allowed_upload()

    def test_version_is_not_allowed_upload(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        for platform in [amo.PLATFORM_LINUX.id,
                         amo.PLATFORM_WIN.id,
                         amo.PLATFORM_BSD.id]:
            file = File(platform_id=platform, version=version)
            file.save()
        assert version.is_allowed_upload()
        file = File(platform_id=amo.PLATFORM_MAC.id, version=version)
        file.save()
        version = Version.uncached.get(pk=81551)
        assert not version.is_allowed_upload()

    def test_version_is_not_allowed_upload_full(self):
        version = Version.objects.get(pk=81551)
        version.files.all().delete()
        for platform in [amo.PLATFORM_LINUX.id,
                         amo.PLATFORM_WIN.id,
                         amo.PLATFORM_MAC.id]:
            file = File(platform_id=platform, version=version)
            file.save()
        assert not version.is_allowed_upload()

    def test_version_is_allowed_upload_search(self):
        version = Version.objects.get(pk=81551)
        version.addon.type = amo.ADDON_SEARCH
        version.addon.save()
        version.files.all()[0].delete()
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
        Version.objects.create(addon=addon)
        eq_(qs.all()[0].status, amo.STATUS_DISABLED)
        addon.current_version.all_files[0]
        assert hide_mock.called

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


class TestViews(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def setUp(self):
        self.old_perpage = views.PER_PAGE
        views.PER_PAGE = 1
        self.addon = Addon.objects.get(id=11730)

    def tearDown(self):
        views.PER_PAGE = self.old_perpage

    def test_version_detail(self):
        base = '/en-US/firefox/addon/%s/versions/' % self.addon.slug
        urls = [(v.version, reverse('addons.versions',
                                    args=[self.addon.slug, v.version]))
                for v in self.addon.versions.all()]

        version, url = urls[0]
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, base + '?page=1#version-%s' % version)

        version, url = urls[1]
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, base + '?page=2#version-%s' % version)

    def test_version_detail_404(self):
        r = self.client.get(reverse('addons.versions',
                                    args=[self.addon.slug, 2]))
        eq_(r.status_code, 404)

    def test_version_link(self):
        addon = Addon.objects.get(id=11730)
        version = addon.current_version.version
        url = reverse('addons.versions', args=[addon.slug])
        doc = PyQuery(self.client.get(url).content)
        link = doc('.version h3 > a').attr('href')
        eq_(link, reverse('addons.versions', args=[addon.slug, version]))
        eq_(doc('.version').attr('id'), 'version-%s' % version)


class TestFeeds(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_feed_elements_present(self):
        """specific elements are present and reasonably well formed"""
        url = reverse('addons.versions.rss', args=['a11730'])
        r = self.client.get(url, follow=True)
        doc = PyQuery(r.content)
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


class TestDownloadsBase(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_5299_gcal', 'base/admin']

    def setUp(self):
        self.addon = Addon.objects.get(id=5299)
        self.file = File.objects.get(id=33046)
        self.beta_file = File.objects.get(id=64874)
        self.file_url = reverse('downloads.file', args=[self.file.id])
        self.latest_url = reverse('downloads.latest', args=[self.addon.slug])

    def assert_served_by_host(self, response, host, file_=None):
        if not file_:
            file_ = self.file
        eq_(response.status_code, 302)
        eq_(response['Location'],
            '%s/%s/%s' % (host, self.addon.id, file_.filename))
        eq_(response['X-Target-Digest'], file_.hash)

    def assert_served_internally(self, response):
        eq_(response.status_code, 200)
        eq_(response['X-SENDFILE'], self.file.guarded_file_path)

    def assert_served_locally(self, response, file_=None, attachment=False):
        host = settings.LOCAL_MIRROR_URL
        if attachment:
            host += '/_attachments'
        self.assert_served_by_host(response, host, file_)

    def assert_served_by_mirror(self, response, file_=None):
        self.assert_served_by_host(response, settings.MIRROR_URL, file_)


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

    def test_admin_disabled_404(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_user_disabled_404(self):
        self.addon.update(disabled_by_user=True)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_file_disabled_404(self):
        self.file.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_file_disabled_ok_for_author(self):
        self.file.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_file_disabled_ok_for_admin(self):
        self.file.update(status=amo.STATUS_DISABLED)
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_author(self):
        # downloads_controller.php claims that add-on authors should be able to
        # download their disabled files.
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_admin_disabled_ok_for_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_author(self):
        self.addon.update(disabled_by_user=True)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_user_disabled_ok_for_admin(self):
        self.addon.update(disabled_by_user=True)
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.assert_served_internally(self.client.get(self.file_url))

    def test_type_attachment(self):
        self.assert_served_by_mirror(self.client.get(self.file_url))
        url = reverse('downloads.file', args=[self.file.id, 'attachment'])
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_nonbrowser_app(self):
        url = self.file_url.replace('firefox', 'thunderbird')
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_mirror_delay(self):
        self.file.datestatuschanged = datetime.now()
        self.file.save()
        self.assert_served_locally(self.client.get(self.file_url))

        t = datetime.now() - timedelta(minutes=settings.MIRROR_DELAY + 10)
        self.file.datestatuschanged = t
        self.file.save()
        self.assert_served_by_mirror(self.client.get(self.file_url))

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


class TestDownloadsLatest(TestDownloadsBase):

    def setUp(self):
        super(TestDownloadsLatest, self).setUp()
        self.platform = Platform.objects.create(id=5)

    def assert_served_by_mirror(self, response):
        # Follow one more hop to hit the downloads.files view.
        r = self.client.get(response['Location'])
        super(TestDownloadsLatest, self).assert_served_by_mirror(r)

    def assert_served_locally(self, response, file_=None, attachment=False):
        # Follow one more hop to hit the downloads.files view.
        r = self.client.get(response['Location'])
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
        p = Platform.objects.create(id=3)
        f = File.objects.create(platform=p, version=self.file.version,
                                filename='unst.xpi')
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.slug, 'platform': 3})
        self.assert_served_locally(self.client.get(url), file_=f)

    def test_query_params(self):
        url = self.latest_url + '?src=xxx'
        r = self.client.get(url)
        eq_(r.status_code, 302)
        assert r['Location'].endswith('?src=xxx'), r['Location']


class TestVersionFromUpload(files.tests.UploadTest, test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/users']

    def setUp(self):
        super(TestVersionFromUpload, self).setUp()
        self.upload = self.get_upload(self.filename)
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(guid='guid@xpi')
        self.platform = Platform.objects.create(id=amo.PLATFORM_MAC.id)
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application_id=1, version=version)


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
                            [Platform.objects.get(pk=amo.PLATFORM_ALL.id)])
        files = version.all_files
        eq_(files[0].filename, u'delicious_bookmarks-0.1-fx.xpi')

    def test_multiple_platforms(self):
        platforms = [Platform.objects.get(pk=amo.PLATFORM_LINUX.id),
                     Platform.objects.get(pk=amo.PLATFORM_MAC.id)]
        assert os.path.exists(self.upload.path)
        with open(self.upload.path) as f:
            uploaded_hash = hashlib.md5(f.read()).hexdigest()
        version = Version.from_upload(self.upload, self.addon, platforms)
        assert not os.path.exists(self.upload.path), (
                "Expected original upload to move but it still exists.")
        files = version.all_files
        eq_(len(files), 2)
        eq_(sorted([f.platform.id for f in files]),
            sorted([p.id for p in platforms]))
        eq_(sorted([f.filename for f in files]),
            [u'delicious_bookmarks-0.1-fx-%s.xpi' % (
                        amo.PLATFORM_LINUX.shortname),
             u'delicious_bookmarks-0.1-fx-%s.xpi' % (
                        amo.PLATFORM_MAC.shortname)])
        for file in files:
            with open(file.file_path) as f:
                eq_(uploaded_hash,
                    hashlib.md5(f.read()).hexdigest(),
                    "md5 hash of %r does not match uploaded file" %
                                                        file.file_path)


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
        eq_(files[0].platform.id, amo.PLATFORM_ALL.id)


class TestMobileVersions(TestMobile):

    def test_versions(self):
        r = self.client.get(reverse('addons.versions', args=['a3615']))
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'versions/mobile/version_list.html')
