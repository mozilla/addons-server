from nose.tools import eq_
from pyquery import PyQuery
import mock
import test_utils

import amo
from amo.urlresolvers import reverse
from addons.models import Addon
from versions import views
from versions.models import Version
from versions.compare import version_int, dict_from_int


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    eq_(version_int("3.5.0a1pre2"), 3050000001002)
    eq_(version_int(""), 200100)


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
