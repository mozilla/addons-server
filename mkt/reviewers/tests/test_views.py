from django.core import mail
from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import AddonUser
import amo
from amo.tests import app_factory, check_links
from amo.urlresolvers import reverse
from amo.utils import urlparams
from devhub.models import ActivityLog
from editors.tests.test_views import EditorTest
from users.models import UserProfile

from mkt.webapps.models import Webapp


class AppReviewerTest(object):
    """Base test class for Markplatce """

    def setUp(self):
        self.login_as_editor()

    def test_403_for_non_editor(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.head(self.url).status_code, 403)

    def test_403_for_anonymous(self):
        self.client.logout()
        eq_(self.client.head(self.url).status_code, 403)


class TestAppQueue(AppReviewerTest, EditorTest):

    def setUp(self):
        self.login_as_editor()
        self.apps = [app_factory(name='XXX',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='YYY',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS)]
        self.url = reverse('reviewers.queue_apps')

    def review_url(self, app, num):
        return urlparams(reverse('reviewers.app_review', args=[app.app_slug]),
                         num=num)

    def test_restricted_results(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = Webapp.objects.pending().order_by('created')
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0], '1')),
            (unicode(apps[1].name), self.review_url(apps[1], '2')),
        ]
        check_links(expected, links, verify=False)

    def test_invalid_page(self):
        r = self.client.get(self.url, {'page': 999})
        eq_(r.status_code, 200)
        eq_(r.context['page'].number, 1)

    def test_queue_count(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.tabnav li a:eq(0)').text(), u'Apps (2)')

    def test_sort(self):
        r = self.client.get(self.url, {'sort': '-name'})
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#addon-queue tbody tr').eq(0).attr('data-addon'),
            str(self.apps[1].id))

    def test_redirect_to_review(self):
        r = self.client.get(self.url, {'num': 2})
        self.assertRedirects(r, self.review_url(self.apps[1], num=2))


class TestReviewApp(AppReviewerTest, EditorTest):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestReviewApp, self).setUp()
        self.app = self.get_app()
        self.app.update(status=amo.STATUS_PENDING)
        self.version = self.app.current_version
        self.url = reverse('reviewers.app_review', args=[self.app.app_slug])

    def get_app(self):
        return Webapp.objects.get(id=337141)

    def post(self, data):
        r = self.client.post(self.url, data)
        self.assertRedirects(r, reverse('reviewers.queue_apps'))

    @mock.patch.object(settings, 'DEBUG', False)
    def test_cannot_review_my_app(self):
        AddonUser.objects.create(addon=self.app,
            user=UserProfile.objects.get(username='editor'))
        eq_(self.client.head(self.url).status_code, 302)

    def test_push_public(self):
        files = list(self.version.files.values_list('id', flat=True))
        self.post({
            'action': 'public',
            'operating_systems': '',
            'applications': '',
            'comments': 'something',
            'addon_files': files,
        })
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0].message().as_string()
        assert 'Your app' in msg, 'Message not customized for apps: %s' % msg

    def test_comment(self):
        self.post({'action': 'comment', 'comments': 'mmm, nice app'})
        eq_(len(mail.outbox), 0)
        comment_version = amo.LOG.COMMENT_VERSION
        eq_(ActivityLog.objects.filter(action=comment_version.id).count(), 1)

    def test_reject(self):
        self.post({'action': 'reject', 'comments': 'suxor'})
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0].message().as_string()
        assert 'Your app' in msg, 'Message not customized for apps: %s' % msg
        eq_(self.get_app().status, amo.STATUS_NULL)
        action = amo.LOG.REJECT_VERSION
        eq_(ActivityLog.objects.filter(action=action.id).count(), 1)
