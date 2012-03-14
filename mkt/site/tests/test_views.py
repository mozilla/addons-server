from django.conf import settings
from django.core import mail

import mock
from nose.tools import eq_

import amo
from amo.urlresolvers import reverse
import amo.tests
import editors.helpers
from addons.models import Addon
from users.models import UserProfile


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


class TestEditorToolsEmailer(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        class FakeRequest:
            user = UserProfile.objects.get(pk=10482).user
        self.request = FakeRequest()
        self.webapp = self.get_webapp()
        self.version = self.webapp.versions.all()[0]

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_notify_email_apps(self):
        helper = editors.helpers.ReviewHelper(request=self.request,
                                              addon=self.webapp,
                                              version=self.version)
        helper.set_data({'comments': 'boop', 'action': 'full'})
        mail.outbox = []
        helper.handler.notify_email('pending_to_public', 'Some subject %s, %s')
        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].body, 'Expected a message'
