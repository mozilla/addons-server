import json

from django.conf import settings
from django.core.cache import cache
from django.test.utils import override_settings

import mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
from test_utils import RequestFactory

import amo
import amo.tests
from amo.urlresolvers import reverse

from mkt.site.urls import template_plus_xframe
from mkt.webapps.models import Webapp


class Test403(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

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
    fixtures = ['webapps/337141-steamcube']

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

    @mock.patch.object(settings, 'USE_APPCACHE', True)
    def test_manifest_appcache(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        content = json.loads(response.content)
        eq_(content['appcache_path'], reverse('django_appcache.manifest'))

    @mock.patch.object(settings, 'USE_APPCACHE', False)
    def test_manifest_no_appcache(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        content = json.loads(response.content)
        assert 'appcache_path' not in content, 'Unexpected: `appcache_path`'

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


class TestHeader(amo.tests.TestCase):
    fixtures = ['base/users']

    def test_auth(self):
        self.client.login(username='regular@mozilla.com', password='password')
        res = self.client.get(reverse('home'))
        eq_(pq(res.content)('head meta[name="DCS.dcsaut"]').attr('content'),
            'yes')

    def test_not(self):
        res = self.client.get(reverse('home'))
        eq_(len(pq(res.content)('head meta[name="DCS.dcsaut"]')), 0)


class TestFooter(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def test_developers_links_to_dashboard(self):
        # No footer in current designs.
        raise SkipTest
        # I've already submitted an app.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        links = pq(r.content)('#site-footer a[rel=external]')
        eq_(links.length, 1)
        eq_(links.attr('href'), reverse('mkt.developers.apps'))

    def test_developers_links_to_landing(self):
        # No footer in current designs.
        raise SkipTest
        # I've ain't got no apps.
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        links = pq(r.content)('#site-footer a[rel=external]')
        eq_(links.length, 1)
        eq_(links.attr('href'), reverse('ecosystem.landing'))

    def test_language_selector(self):
        # No footer in current designs.
        raise SkipTest
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#lang-form option[selected]').attr('value'),
            'en-us')

    def test_language_selector_variables(self):
        # No footer in current designs.
        raise SkipTest
        r = self.client.get(reverse('home'), {'x': 'xxx', 'y': 'yyy'})
        doc = pq(r.content)('#lang-form')
        eq_(doc('input[type=hidden][name=x]').attr('value'), 'xxx')
        eq_(doc('input[type=hidden][name=y]').attr('value'), 'yyy')


class TestXLegalFrame(amo.tests.TestCase):

    def setUp(self):
        self.request = RequestFactory()
        self.request.groups = ()
        self.request.user = mock.Mock()
        self.request.MOBILE = self.request.TABLET = self.request.GAIA = True
        self.request.is_ajax = mock.Mock()
        self.request.META = {'HTTP_USER_AGENT': ''}

    @mock.patch.object(settings, 'LEGAL_XFRAME_ALLOW_FROM', ['omg.org'])
    def test_allow(self):
        self.request.META['HTTP_REFERER'] = 'http://omg.org/yes'
        res = template_plus_xframe(self.request, 'site/privacy-policy.html')
        eq_(res['x-frame-options'], 'allow-from omg.org')

    @mock.patch.object(settings, 'LEGAL_XFRAME_ALLOW_FROM', ['omg.org'])
    def test_deny(self):
        for referrer in ('', 'http://omg.xxx/yes', '!#*@ YOU, @#($!#$(&%*#^'):
            self.request.META['HTTP_REFERER'] = referrer
            res = template_plus_xframe(self.request,
                                       'site/privacy-policy.html')
            assert 'x-frame-options' not in res, (
                'Unexpected headers for referrer %r: %s' % (referrer,
                                                            res._headers))
