from datetime import datetime, timedelta
from django.conf import settings

import mock
import test_utils
from nose.tools import eq_
from pyquery import PyQuery

import amo
from amo.urlresolvers import reverse
from addons.models import Addon
from files.models import File, Platform
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
    fixtures = ['base/addon_3615']

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


class TestViews(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def setUp(self):
        self.old_perpage = views.PER_PAGE
        views.PER_PAGE = 1

    def tearDown(self):
        views.PER_PAGE = self.old_perpage

    def test_version_detail(self):
        base = '/en-US/firefox/addon/11730/versions/'
        a = Addon.objects.get(id=11730)
        urls = [(v.version, reverse('addons.versions', args=[a.id, v.version]))
                for v in a.versions.all()]

        version, url = urls[0]
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, base + '?page=1#version-%s' % version)

        version, url = urls[1]
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, base + '?page=2#version-%s' % version)

    def test_version_detail_404(self):
        r = self.client.get(reverse('addons.versions', args=[11730, 2]))
        eq_(r.status_code, 404)

    def test_version_link(self):
        addon = Addon.objects.get(id=11730)
        version = addon.current_version.version
        url = reverse('addons.versions', args=[addon.id])
        doc = PyQuery(self.client.get(url).content)
        link = doc('.version h3 > a').attr('href')
        eq_(link, reverse('addons.versions', args=[addon.id, version]))
        eq_(doc('.version').attr('id'), 'version-%s' % version)


class TestFeeds(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon', 'base/apps']

    def test_feed_elements_present(self):
        """specific elements are present and reasonably well formed"""
        url = reverse('addons.versions.rss', args=[11730])
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
        assert item_link.text.endswith('/addon/11730/versions/20090521')
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
        self.latest_url = reverse('downloads.latest', args=[self.addon.id])

    def assert_served_by_host(self, response, host, file_=None):
        if not file_:
            file_ = self.file
        eq_(response.status_code, 302)
        eq_(response['Location'],
            '%s/%s/%s' % (host, self.addon.id, file_.filename))
        eq_(response['X-Target-Digest'], file_.hash)

    def assert_served_locally(self, response, file_=None, attachment=False):
        host = settings.LOCAL_MIRROR_URL
        if attachment:
            host += '/_attachments'
        self.assert_served_by_host(response, host, file_)

    def assert_served_by_mirror(self, response):
        self.assert_served_by_host(response, settings.MIRROR_URL)


class TestDownloads(TestDownloadsBase):

    def test_file_404(self):
        r = self.client.get(reverse('downloads.file', args=[234]))
        eq_(r.status_code, 404)

    def test_public(self):
        eq_(self.addon.status, 4)
        eq_(self.file.status, 4)
        self.assert_served_by_mirror(self.client.get(self.file_url))

    def test_public_addon_unreviewed_file(self):
        self.file.status = amo.STATUS_UNREVIEWED
        self.file.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_unreviewed_addon(self):
        self.addon.status = amo.STATUS_PENDING
        self.addon.save()
        self.assert_served_locally(self.client.get(self.file_url))

    def test_disabled_404(self):
        self.addon.status = amo.STATUS_DISABLED
        self.addon.save()
        eq_(self.client.get(self.file_url).status_code, 404)

    def test_disabled_author(self):
        # downloads_controller.php claims that add-on authors should be able to
        # download their disabled files.
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='g@gmail.com', password='password')
        self.assert_served_locally(self.client.get(self.file_url))

    def test_disabled_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.assert_served_locally(self.client.get(self.file_url))

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
        self.assert_served_locally(self.client.get(url), self.beta_file)

    def test_null_datestatuschanged(self):
        self.file.update(datestatuschanged=None)
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

    def test_success(self):
        assert self.addon.current_version
        self.assert_served_by_mirror(self.client.get(self.latest_url))

    def test_platform(self):
        # We still match PLATFORM_ALL.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.id, 'platform': 5})
        self.assert_served_by_mirror(self.client.get(url))

        # And now we match the platform in the url.
        self.file.platform = self.platform
        self.file.save()
        self.assert_served_by_mirror(self.client.get(url))

        # But we can't match platform=3.
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.id, 'platform': 3})
        eq_(self.client.get(url).status_code, 404)

    def test_type(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.id, 'type': 'attachment'})
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_and_type(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.id, 'platform': 5,
                              'type': 'attachment'})
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_trailing_filename(self):
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.id, 'platform': 5,
                              'type': 'attachment'})
        url += self.file.filename
        self.assert_served_locally(self.client.get(url), attachment=True)

    def test_platform_multiple_objects(self):
        p = Platform.objects.create(id=3)
        f = File.objects.create(platform=p, version=self.file.version,
                                filename='unst.xpi')
        url = reverse('downloads.latest',
                      kwargs={'addon_id': self.addon.id, 'platform': 3})
        self.assert_served_locally(self.client.get(url), file_=f)

    def test_query_params(self):
        url = self.latest_url + '?src=xxx'
        r = self.client.get(url)
        eq_(r.status_code, 302)
        assert r['Location'].endswith('?src=xxx'), r['Location']
