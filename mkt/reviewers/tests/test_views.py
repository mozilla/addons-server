import time

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
from devhub.models import AppLog
from editors.models import CannedResponse
from editors.tests.test_views import EditorTest
from users.models import UserProfile

from mkt.webapps.models import Webapp


class AppReviewerTest(object):

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

    def _check_email(self, msg, subject):
        eq_(msg.to, list(self.app.authors.values_list('email', flat=True)))
        eq_(msg.subject, '%s: %s' % (subject, self.app.name))
        eq_(msg.from_email, settings.NOBODY_EMAIL)
        eq_(msg.extra_headers['Reply-To'], settings.MKT_REVIEWERS_EMAIL)

    def _check_admin_email(self, msg, subject):
        eq_(msg.to, [settings.MKT_SENIOR_EDITORS_EMAIL])
        eq_(msg.subject, '%s: %s' % (subject, self.app.name))
        eq_(msg.from_email, settings.NOBODY_EMAIL)
        eq_(msg.extra_headers['Reply-To'], settings.MKT_REVIEWERS_EMAIL)

    def _check_email_body(self, msg):
        body = msg.message().as_string()
        url = self.app.get_url_path(add_prefix=False)
        assert url in body, 'Could not find apps detail URL in %s' % msg

    def _check_log(self, action):
        assert AppLog.objects.filter(addon=self.app,
                        activity_log__action=action.id).exists(), (
            "Didn't find `%s` action in logs." % action.short)

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
        self._check_log(amo.LOG.APPROVE_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved')
        self._check_email_body(msg)

    def test_push_public_waiting(self):
        files = list(self.version.files.values_list('id', flat=True))
        self.get_app().update(make_public=amo.PUBLIC_WAIT)
        self.post({
            'action': 'public',
            'operating_systems': '',
            'applications': '',
            'comments': 'something',
            'addon_files': files,
        })
        eq_(self.get_app().status, amo.STATUS_PUBLIC_WAITING)
        self._check_log(amo.LOG.APPROVE_VERSION_WAITING)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved but waiting')
        self._check_email_body(msg)

    def test_comment(self):
        self.post({'action': 'comment', 'comments': 'mmm, nice app'})
        eq_(len(mail.outbox), 0)
        self._check_log(amo.LOG.COMMENT_VERSION)

    def test_reject(self):
        self.post({'action': 'reject', 'comments': 'suxor'})
        eq_(self.get_app().status, amo.STATUS_REJECTED)
        self._check_log(amo.LOG.REJECT_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)

    def test_super_review(self):
        self.post({'action': 'super', 'comments': 'soup her man'})
        eq_(self.get_app().admin_review, True)
        self._check_log(amo.LOG.REQUEST_SUPER_REVIEW)
        # Test 2 emails: 1 to dev, 1 to admin.
        eq_(len(mail.outbox), 2)
        dev_msg = mail.outbox[0]
        self._check_email(dev_msg, 'Submission Update')
        adm_msg = mail.outbox[1]
        self._check_admin_email(adm_msg, 'Super Review Requested')

    def test_more_information(self):
        self.post({'action': 'info', 'comments': 'Knead moor in faux'})
        eq_(self.get_app().status, amo.STATUS_PENDING)
        self._check_log(amo.LOG.REQUEST_INFORMATION)
        vqs = self.get_app().versions.all()
        eq_(vqs.count(), 1)
        eq_(vqs.filter(has_info_request=True).count(), 1)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')


class TestCannedResponses(EditorTest):

    def setUp(self):
        super(TestCannedResponses, self).setUp()
        self.login_as_editor()
        self.app = app_factory(name='XXX',
                               status=amo.WEBAPPS_UNREVIEWED_STATUS)
        self.cr_addon = CannedResponse.objects.create(
            name=u'addon reason', response=u'addon reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_ADDON)
        self.cr_app = CannedResponse.objects.create(
            name=u'app reason', response=u'app reason body',
            sort_group=u'public', type=amo.CANNED_RESPONSE_APP)
        self.url = reverse('reviewers.app_review', args=[self.app.app_slug])

    def test_no_addon(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        form = r.context['form']
        choices = form.fields['canned_response'].choices[1][1]
        # choices is grouped by the sort_group, where choices[0] is the
        # default "Choose a response..." option.
        # Within that, it's paired by [group, [[response, name],...]].
        # So above, choices[1][1] gets the first real group's list of
        # responses.
        eq_(len(choices), 1)
        assert self.cr_app.response in choices[0]
        assert self.cr_addon.response not in choices[0]


class TestReviewLog(EditorTest):

    def setUp(self):
        self.login_as_editor()
        super(TestReviewLog, self).setUp()
        self.login_as_editor()
        self.apps = [app_factory(name='XXX',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='YYY',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS)]
        self.url = reverse('reviewers.logs')

    def get_user(self):
        return UserProfile.objects.all()[0]

    def make_approvals(self):
        for app in self.apps:
            amo.log(amo.LOG.REJECT_VERSION, app, app.current_version,
                    user=self.get_user(), details={'comments': 'youwin'})

    def make_an_approval(self, action, comment='youwin', username=None,
                         app=None):
        if username:
            user = UserProfile.objects.get(username=username)
        else:
            user = self.get_user()
        if not app:
            app = self.apps[0]
        amo.log(action, app, app.current_version, user=user,
                details={'comments': comment})

    def test_basic(self):
        self.make_approvals()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        assert doc('#log-filter button'), 'No filters.'
        # Should have 2 showing.
        rows = doc('tbody tr')
        eq_(rows.filter(':not(.hide)').length, 2)
        eq_(rows.filter('.hide').eq(0).text(), 'youwin')

    def test_xss(self):
        a = self.apps[0]
        a.name = '<script>alert("xss")</script>'
        a.save()
        amo.log(amo.LOG.REJECT_VERSION, a, a.current_version,
                user=self.get_user(), details={'comments': 'xss!'})

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        inner_html = pq(r.content)('#log-listing tbody td').eq(1).html()

        assert '&lt;script&gt;' in inner_html
        assert '<script>' not in inner_html

    def test_end_filter(self):
        """
        Let's use today as an end-day filter and make sure we see stuff if we
        filter.
        """
        self.make_approvals()
        # Make sure we show the stuff we just made.
        date = time.strftime('%Y-%m-%d')
        r = self.client.get(self.url, dict(end=date))
        eq_(r.status_code, 200)
        doc = pq(r.content)('#log-listing tbody')
        eq_(doc('tr:not(.hide)').length, 2)
        eq_(doc('tr.hide').eq(0).text(), 'youwin')

    def test_end_filter_wrong(self):
        """
        Let's use today as an end-day filter and make sure we see stuff if we
        filter.
        """
        self.make_approvals()
        r = self.client.get(self.url, dict(end='wrong!'))
        # If this is broken, we'll get a traceback.
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#log-listing tr:not(.hide)').length, 3)

    def test_search_comment_exists(self):
        """Search by comment."""
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, comment='hello')
        r = self.client.get(self.url, dict(search='hello'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#log-listing tbody tr.hide').eq(0).text(), 'hello')

    def test_search_comment_doesnt_exist(self):
        """Search by comment, with no results."""
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, comment='hello')
        r = self.client.get(self.url, dict(search='bye'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    def test_search_author_exists(self):
        """Search by author."""
        self.make_approvals()
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, username='editor',
                              comment='hi')

        r = self.client.get(self.url, dict(search='editor'))
        eq_(r.status_code, 200)
        rows = pq(r.content)('#log-listing tbody tr')

        eq_(rows.filter(':not(.hide)').length, 1)
        eq_(rows.filter('.hide').eq(0).text(), 'hi')

    def test_search_author_doesnt_exist(self):
        """Search by author, with no results."""
        self.make_approvals()
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, username='editor')

        r = self.client.get(self.url, dict(search='wrong'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    def test_search_addon_exists(self):
        """Search by add-on name."""
        self.make_approvals()
        app = self.apps[0]
        r = self.client.get(self.url, dict(search=app.name))
        eq_(r.status_code, 200)
        tr = pq(r.content)('#log-listing tr[data-addonid="%s"]' % app.id)
        eq_(tr.length, 1)
        eq_(tr.siblings('.comments').text(), 'youwin')

    def test_search_addon_by_slug_exists(self):
        """Search by app slug."""
        app = self.apps[0]
        app.app_slug = 'a-fox-was-sly'
        app.save()
        self.make_approvals()
        r = self.client.get(self.url, dict(search='fox'))
        eq_(r.status_code, 200)
        tr = pq(r.content)('#log-listing tr[data-addonid="%s"]' % app.id)
        eq_(tr.length, 1)
        eq_(tr.siblings('.comments').text(), 'youwin')

    def test_search_addon_doesnt_exist(self):
        """Search by add-on name, with no results."""
        self.make_approvals()
        r = self.client.get(self.url, dict(search='zzz'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    @mock.patch('devhub.models.ActivityLog.arguments', new=mock.Mock)
    def test_addon_missing(self):
        self.make_approvals()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td').eq(1).text(),
            'App has been deleted.')

    def test_request_info_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_INFORMATION)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td a').eq(1).text(),
            'More information requested')

    def test_super_review_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td a').eq(1).text(),
            'Super review requested')
