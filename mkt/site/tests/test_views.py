import json
from urlparse import urljoin

from django.conf import settings
from django.core.cache import cache
from django.test.utils import override_settings

import mock
from lxml import etree
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse

from mkt.webapps.models import Webapp

from mkt.site.fixtures import fixture

class Test403(amo.tests.TestCase):
    fixtures = ['base/users'] + fixture('webapp_337141')

    def setUp(self):
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def _test_403(self, url):
        res = self.client.get(url, follow=True)
        eq_(res.status_code, 403)
        self.assertTemplateUsed(res, 'site/403.html')

    def test_403_admin(self):
        self._test_403('/admin')

    def test_403_devhub(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        app = Webapp.objects.get(pk=337141)
        self._test_403(app.get_dev_url('edit'))

    def test_403_reviewer(self):
        self._test_403('/reviewers')


class Test404(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def _test_404(self, url):
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 404)
        self.assertTemplateUsed(r, 'site/404.html')
        return r

    def test_404(self):
        self._test_404('/xxx')

    def test_404_devhub(self):
        self._test_404('/developers/xxx')

    def test_404_consumer_legacy(self):
        self._test_404('/xxx')

    def test_404_consumer(self):
        self._test_404('/xxx')

    def test_404_api(self):
        res = self.client.get('/api/this-should-never-work/')
        eq_(res.status_code, 404)
        eq_(res.content, '')


class TestManifest(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('manifest.webapp')

    @mock.patch('mkt.carriers.carriers.CARRIERS', {'boop': 'boop'})
    @mock.patch.object(settings, 'WEBAPP_MANIFEST_NAME', 'Firefox Marketplace')
    @mock.patch('mkt.site.views.get_carrier')
    def test_manifest(self, mock_get_carrier):
        mock_get_carrier.return_value = 'boop'
        response = self.client.get(reverse('manifest.webapp'))
        eq_(response.status_code, 200)
        eq_(response['Content-Type'], 'application/x-web-app-manifest+json')
        content = json.loads(response.content)
        eq_(content['name'], 'Firefox Marketplace')
        url = reverse('manifest.webapp')
        assert 'en-US' not in url and 'firefox' not in url
        eq_(content['launch_path'], '/?carrier=boop')

    @mock.patch('mkt.carriers.carriers.CARRIERS', [])
    def test_manifest_no_carrier(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        content = json.loads(response.content)
        assert 'launch_path' not in content

    @mock.patch.object(settings, 'WEBAPP_MANIFEST_NAME', 'Mozilla Fruitstand')
    def test_manifest_name(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        content = json.loads(response.content)
        eq_(content['name'], 'Mozilla Fruitstand')

    def test_manifest_orientation(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        content = json.loads(response.content)
        eq_(content['orientation'], ['portrait-primary'])

    def test_manifest_etag(self):
        resp = self.client.get(self.url)
        etag = resp.get('Etag')
        assert etag, 'Missing ETag'

        # Trigger a change to the manifest by changing the name.
        with self.settings(WEBAPP_MANIFEST_NAME='Mozilla Fruitstand'):
            resp = self.client.get(self.url)
            assert resp.get('Etag'), 'Missing ETag'
            self.assertNotEqual(etag, resp.get('Etag'))

    def test_conditional_get_manifest(self):
        resp = self.client.get(self.url)
        etag = resp.get('Etag')

        resp = self.client.get(self.url, HTTP_IF_NONE_MATCH=str(etag))
        eq_(resp.content, '')
        eq_(resp.status_code, 304)


class TestMozmarketJS(amo.tests.TestCase):

    def setUp(self):
        cache.clear()

    def render(self):
        return self.client.get(reverse('site.mozmarket_js'))

    @mock.patch.object(settings, 'SITE_URL', 'https://secure-mkt.com/')
    @mock.patch.object(settings, 'MINIFY_MOZMARKET', False)
    def test_render(self):
        resp = self.render()
        self.assertContains(resp, "var server = 'https://secure-mkt.com/'")
        eq_(resp['Content-Type'], 'text/javascript')

    @mock.patch.object(settings, 'SITE_URL', 'https://secure-mkt.com/')
    @mock.patch.object(settings, 'MINIFY_MOZMARKET', True)
    def test_minify(self):
        resp = self.render()
        # Check for no space after equal sign.
        self.assertContains(resp, '="https://secure-mkt.com/"')

    @mock.patch.object(settings, 'MINIFY_MOZMARKET', True)
    @mock.patch.object(settings, 'UGLIFY_BIN', None)
    def test_minify_with_yui(self):
        self.render()  # no errors

    @mock.patch.object(settings, 'MINIFY_MOZMARKET', False)
    def test_receiptverifier(self):
        resp = self.render()
        self.assertContains(resp, 'exports.receipts.Verifier')

    @mock.patch.object(settings, 'MOZMARKET_VENDOR_EXCLUDE',
                       ['receiptverifier'])
    @mock.patch.object(settings, 'MINIFY_MOZMARKET', False)
    def test_exclude(self):
        resp = self.render()
        self.assertNotContains(resp, 'exports.receipts.Verifier')


class TestRobots(amo.tests.TestCase):

    @override_settings(CARRIER_URLS=['seavanworld'])
    @override_settings(ENGAGE_ROBOTS=True)
    def test_engage_robots(self):
        rs = self.client.get('/robots.txt')
        self.assertContains(rs, 'Allow: /')
        self.assertContains(rs, 'Disallow: /seavanworld/')

    @override_settings(ENGAGE_ROBOTS=False)
    def test_do_not_engage_robots(self):
        rs = self.client.get('/robots.txt')
        self.assertContains(rs, 'Disallow: /')


class TestOpensearch(amo.tests.TestCase):

    def test_opensearch_declaration(self):
        """Look for opensearch declaration in templates."""

        response = self.client.get(reverse('commonplace.fireplace'))
        elm = pq(response.content)(
            'link[rel=search][type="application/opensearchdescription+xml"]')
        eq_(elm.attr('href'), reverse('opensearch'))
        eq_(elm.attr('title'), 'Firefox Marketplace')

    def test_opensearch(self):
        response = self.client.get(reverse('opensearch'))
        eq_(response['Content-Type'], 'text/xml')
        eq_(response.status_code, 200)
        doc = etree.fromstring(response.content)
        e = doc.find('{http://a9.com/-/spec/opensearch/1.1/}ShortName')
        eq_(e.text, 'Firefox Marketplace')
        e = doc.find('{http://a9.com/-/spec/opensearch/1.1/}Url')
        wanted = '%s?q={searchTerms}' % urljoin(settings.SITE_URL, '/search')
        eq_(e.attrib['template'], wanted)
