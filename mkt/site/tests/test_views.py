import json

from django.conf import settings

import mock
from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse


class Test404(amo.tests.TestCase):

    def test_404(self):
        response = self.client.get('/xxx', follow=True)
        eq_(response.status_code, 404)
        self.assertTemplateUsed(response, 'site/404.html')


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
