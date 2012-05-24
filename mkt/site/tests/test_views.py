import json

from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse


class Test404(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def _test_404(self, url):
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 404)
        self.assertTemplateUsed(r, 'site/404.html')
        return r

    def test_404(self):
        r = self._test_404('/xxx')
        eq_(pq(r.content)('#site-header h1').text(), 'Mozilla Marketplace')

    def test_404_devhub(self):
        # TODO: Remove log-in bit when we remove `request.can_view_consumer`.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        r = self._test_404('/developers/xxx')
        eq_(pq(r.content)('#site-header h1').text(),
            'Mozilla Marketplace Developers')

    def test_404_consumer_legacy(self):
        r = self._test_404('/xxx')
        eq_(pq(r.content)('#site-header h1').text(), 'Mozilla Marketplace')

    def test_404_consumer(self):
        # TODO: Remove log-in bit when we remove `request.can_view_consumer`.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        r = self._test_404('/xxx')
        eq_(pq(r.content)('#site-header h1').text(), 'Mozilla Marketplace')


class TestManifest(amo.tests.TestCase):

    def test_manifest(self):
        response = self.client.get(reverse('manifest.webapp'))
        eq_(response.status_code, 200)
        eq_(response['Content-Type'], 'application/x-web-app-manifest+json')
        content = json.loads(response.content)
        eq_(content['name'], 'Mozilla Marketplace')
        eq_(content['default_locale'], 'en-US')
        url = reverse('manifest.webapp')
        assert 'en-US' not in url and 'firefox' not in url


class TestMozmarketJS(amo.tests.TestCase):

    @mock.patch.object(settings, 'SITE_URL', 'https://secure-mkt.com/')
    def test_render(self):
        resp = self.client.get(reverse('site.mozmarket_js'))
        self.assertContains(resp, "var server = 'https://secure-mkt.com/'")
        eq_(resp['Content-Type'], 'text/javascript')


class TestRobots(amo.tests.TestCase):

    @mock.patch.object(settings, 'ENGAGE_ROBOTS', True)
    def test_engage_robots(self):
        rs = self.client.get('/robots.txt')
        self.assertContains(rs, 'Allow: /')

    @mock.patch.object(settings, 'ENGAGE_ROBOTS', False)
    def test_do_not_engage_robots(self):
        rs = self.client.get('/robots.txt')
        self.assertContains(rs, 'Disallow: /')


class TestFooter(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def test_developers_links_to_dashboard(self):
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        f = pq(r.content)('#site-footer')
        eq_(f.find('a[href="%s"]' % reverse('mkt.developers.index')).length, 1)
        eq_(f.find('a[href="%s"]' % reverse('ecosystem.landing')).length, 0)

    def test_developers_links_to_landing(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        f = pq(r.content)('#site-footer')
        eq_(f.find('a[href="%s"]' % reverse('mkt.developers.index')).length, 0)
        eq_(f.find('a[href="%s"]' % reverse('ecosystem.landing')).length, 1)

    def test_language_selector(self):
        # TODO: Remove log-in bit when we remove `request.can_view_consumer`.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#lang-form option[selected]').attr('value'),
            'en-us')

    def test_language_selector_variables(self):
        # TODO: Remove log-in bit when we remove `request.can_view_consumer`.
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('home'), {'x': 'xxx', 'y': 'yyy'})
        doc = pq(r.content)('#lang-form')
        eq_(doc('input[type=hidden][name=x]').attr('value'), 'xxx')
        eq_(doc('input[type=hidden][name=y]').attr('value'), 'yyy')


class TestCSRF(amo.tests.TestCase):
    fixtures = ['base/users']

    def test_csrf(self):
        assert json.loads(self.client.post(reverse('csrf')).content)['csrf']

    def test_not_csrf(self):
        self.client.login(username='admin@mozilla.com', password='password')
        eq_(self.client.post(reverse('csrf')).status_code, 403)
