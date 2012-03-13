from django.conf import settings

import mock
from nose.tools import eq_

import amo
from amo.urlresolvers import reverse
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


class TestEditorTools(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def test_home(self):
        eq_(self.client.get(reverse('editors.home')).status_code, 200)
        eq_(self.client.get(reverse('editors.queue_apps')).status_code, 200)

    def _test_review(self, status):
        app = amo.tests.addon_factory(type=amo.ADDON_WEBAPP, status=status)
        r = self.client.get(reverse('editors.review', args=[app.slug]))
        eq_(r.status_code, 200)

    def test_review_pending(self):
        self._test_review(amo.WEBAPPS_UNREVIEWED_STATUS)

    def test_review_public(self):
        self._test_review(amo.STATUS_PUBLIC)
