import json

from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.urlresolvers import reverse


class Test404(amo.tests.TestCase):

    def _test_404(self, url):
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 404)
        self.assertTemplateUsed(r, 'site/404.html')
        return r

    def test_404(self):
        r = self._test_404('/xxx')
        eq_(pq(r.content)('#site-header h1').text(),
            'Marketplace Developer Hub')

    def test_404_devhub(self):
        waffle.models.Switch.objects.create(name='unleash-consumer',
                                            active=True)
        r = self._test_404('/developers/xxx')
        eq_(pq(r.content)('#site-header h1').text(),
            'Marketplace Developer Hub')

    def test_404_consumer(self):
        waffle.models.Switch.objects.create(name='unleash-consumer',
                                            active=True)
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

    def test_language_selector(self):
        waffle.models.Switch.objects.create(name='unleash-consumer',
                                            active=True)
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#lang-form option[selected]').attr('value'),
            'en-us')

    def test_language_selector_variables(self):
        waffle.models.Switch.objects.create(name='unleash-consumer',
                                            active=True)
        r = self.client.get(reverse('home'), {'x': 'xxx', 'y': 'yyy'})
        doc = pq(r.content)('#lang-form')
        eq_(doc('input[type=hidden][name=x]').attr('value'), 'xxx')
        eq_(doc('input[type=hidden][name=y]').attr('value'), 'yyy')


class TestCSRF(amo.tests.TestCase):
    fixtures = ['base/users']

    def test_csrf(self):
        assert json.loads(self.client.get(reverse('csrf')).content)['csrf']

    def test_not_csrf(self):
        self.client.login(username='admin@mozilla.com', password='password')
        eq_(self.client.get(reverse('csrf')).status_code, 403)
