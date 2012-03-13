from django.conf import settings

import mock
from nose.tools import eq_

import amo.tests


class Test404(amo.tests.TestCase):

    def test_404(self):
        response = self.client.get('/xxx', follow=True)
        eq_(response.status_code, 404)
        self.assertTemplateUsed(response, 'site/404.html')


class TestRobots(amo.tests.TestCase):

    @mock.patch.object(settings, 'ENGAGE_ROBOTS', True)
    def test_engage_robots(self):
        rs = self.client.get('/robots.txt')
        self.assertContains(rs, 'Allow: /')

    @mock.patch.object(settings, 'ENGAGE_ROBOTS', False)
    def test_do_not_engage_robots(self):
        rs = self.client.get('/robots.txt')
        self.assertContains(rs, 'Disallow: /')
