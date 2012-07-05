# -*- coding: utf-8 -*-
import datetime
from itertools import cycle
import json
import time

from django.core import mail
from django.conf import settings

import mock
from nose.tools import eq_, ok_
from pyquery import PyQuery as pq
import waffle

import amo
from abuse.models import AbuseReport
from access.models import Group, GroupUser
from addons.models import AddonDeviceType, AddonUser, DeviceType
from amo.tests import app_factory, check_links
from amo.urlresolvers import reverse
from amo.utils import urlparams
from devhub.models import AppLog
from editors.models import CannedResponse, ReviewerScore
from users.models import UserProfile
from zadmin.models import get_config, set_config

from mkt.reviewers.models import EscalationQueue, RereviewQueue
from mkt.webapps.models import Webapp


class AppReviewerTest(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.login_as_editor()

    def login_as_admin(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def login_as_editor(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def check_actions(self, expected, elements):
        """Check the action buttons on the review page.

        `expected` is a list of tuples containing action name and action form
        value.  `elements` is a PyQuery list of input elements.

        """
        for idx, item in enumerate(expected):
            text, form_value = item
            e = elements.eq(idx)
            eq_(e.parent().text(), text)
            eq_(e.attr('name'), 'action')
            eq_(e.val(), form_value)


class AccessMixin(object):

    def test_403_for_non_editor(self, *args, **kwargs):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.head(self.url).status_code, 403)

    def test_302_for_anonymous(self, *args, **kwargs):
        self.client.logout()
        eq_(self.client.head(self.url).status_code, 302)


class TestReviewersHome(AppReviewerTest, AccessMixin):

    def setUp(self):
        self.login_as_editor()
        super(TestReviewersHome, self).setUp()
        self.apps = [app_factory(name='Antelope',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='Bear',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='Cougar',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS)]
        self.url = reverse('reviewers.home')

    def test_stats_waiting(self):
        now = datetime.datetime.now()
        days_ago = lambda n: now - datetime.timedelta(days=n)

        self.apps[0].update(created=days_ago(1))
        self.apps[1].update(created=days_ago(5))
        self.apps[2].update(created=days_ago(15))

        doc = pq(self.client.get(self.url).content)

        # Total unreviewed apps.
        eq_(doc('.editor-stats-title a').text(), '3 Pending App Reviews')
        # Unreviewed submissions in the past week.
        ok_('2 unreviewed app submissions' in
            doc('.editor-stats-table > div').text())
        # Maths.
        eq_(doc('.waiting_new').attr('title')[-3:], '33%')
        eq_(doc('.waiting_med').attr('title')[-3:], '33%')
        eq_(doc('.waiting_old').attr('title')[-3:], '33%')

    def test_reviewer_leaders(self):
        reviewers = UserProfile.objects.all()[:2]
        # 1st user reviews 2, 2nd user only 1.
        users = cycle(reviewers)
        for app in self.apps:
            amo.log(amo.LOG.APPROVE_VERSION, app, app.current_version,
                    user=users.next(), details={'comments': 'hawt'})

        doc = pq(self.client.get(self.url).content.decode('utf-8'))

        # Top Reviews.
        table = doc('#editors-stats .editor-stats-table').eq(0)
        eq_(table.find('td').eq(0).text(), reviewers[0].name)
        eq_(table.find('td').eq(1).text(), u'2')
        eq_(table.find('td').eq(2).text(), reviewers[1].name)
        eq_(table.find('td').eq(3).text(), u'1')

        # Top Reviews this month.
        table = doc('#editors-stats .editor-stats-table').eq(1)
        eq_(table.find('td').eq(0).text(), reviewers[0].name)
        eq_(table.find('td').eq(1).text(), u'2')
        eq_(table.find('td').eq(2).text(), reviewers[1].name)
        eq_(table.find('td').eq(3).text(), u'1')


class TestAppQueue(AppReviewerTest, AccessMixin):
    fixtures = ['base/devicetypes', 'base/users']

    def setUp(self):

        now = datetime.datetime.now()
        days_ago = lambda n: now - datetime.timedelta(days=n)

        self.apps = [app_factory(name='XXX',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='YYY',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='ZZZ')]
        self.apps[0].update(created=days_ago(2))
        self.apps[1].update(created=days_ago(1))

        RereviewQueue.objects.create(addon=self.apps[2])

        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_pending')

    def review_url(self, app, num):
        return urlparams(reverse('reviewers.apps.review', args=[app.app_slug]),
                         num=num, tab='pending')

    def test_template_links(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = Webapp.objects.pending().order_by('created')
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0], '1')),
            (unicode(apps[1].name), self.review_url(apps[1], '2')),
        ]
        check_links(expected, links, verify=False)

    def test_action_buttons(self):
        r = self.client.get(self.review_url(self.apps[0], '1'))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Reject', 'reject'),
            (u'Request more information', 'info'),
            (u'Request super-review', 'super'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_flag_super_review(self):
        self.apps[0].update(admin_review=True)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(3)')
        flags = tds('div.ed-sprite-admin-review')
        eq_(flags.length, 1)

    def test_flag_info(self):
        self.apps[0].current_version.update(has_info_request=True)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(3)')
        flags = tds('div.ed-sprite-info')
        eq_(flags.length, 1)

    def test_flag_comment(self):
        self.apps[0].current_version.update(has_editor_comment=True)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(3)')
        flags = tds('div.ed-sprite-editor')
        eq_(flags.length, 1)

    def test_devices(self):
        AddonDeviceType.objects.create(
            addon=self.apps[0], device_type=DeviceType.objects.get(pk=1))
        AddonDeviceType.objects.create(
            addon=self.apps[0], device_type=DeviceType.objects.get(pk=2))
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(5)')
        eq_(tds('ul li:not(.unavailable)').length, 2)

    def test_payments(self):
        self.apps[0].update(premium_type=amo.ADDON_PREMIUM)
        self.apps[1].update(premium_type=amo.ADDON_FREE_INAPP)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(6)')
        eq_(tds.eq(0).text(), amo.ADDON_PREMIUM_TYPES[amo.ADDON_PREMIUM])
        eq_(tds.eq(1).text(), amo.ADDON_PREMIUM_TYPES[amo.ADDON_FREE_INAPP])

    def test_abuse(self):
        AbuseReport.objects.create(addon=self.apps[0], message='!@#$')
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(7)')
        eq_(tds.eq(0).text(), '1')

    def test_invalid_page(self):
        r = self.client.get(self.url, {'page': 999})
        eq_(r.status_code, 200)
        eq_(r.context['pager'].number, 1)

    def test_queue_count(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (2)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (1)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Escalations (0)')

    # TODO(robhudson): Add sorting back in.
    #def test_sort(self):
    #    r = self.client.get(self.url, {'sort': '-name'})
    #    eq_(r.status_code, 200)
    #    eq_(pq(r.content)('#addon-queue tbody tr').eq(0).attr('data-addon'),
    #        str(self.apps[1].id))

    def test_redirect_to_review(self):
        r = self.client.get(self.url, {'num': 2})
        self.assertRedirects(r, self.review_url(self.apps[1], num=2))


class TestRereviewQueue(AppReviewerTest, AccessMixin):
    fixtures = ['base/devicetypes', 'base/users']

    def setUp(self):
        now = datetime.datetime.now()
        days_ago = lambda n: now - datetime.timedelta(days=n)

        self.apps = [app_factory(name='XXX'),
                     app_factory(name='YYY'),
                     app_factory(name='ZZZ')]

        rq1 = RereviewQueue.objects.create(addon=self.apps[0])
        rq1.update(created=days_ago(5))
        rq2 = RereviewQueue.objects.create(addon=self.apps[1])
        rq2.update(created=days_ago(3))
        rq3 = RereviewQueue.objects.create(addon=self.apps[2])
        rq3.update(created=days_ago(1))

        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_rereview')

    def review_url(self, app, num):
        return urlparams(reverse('reviewers.apps.review', args=[app.app_slug]),
                         num=num, tab='rereview')

    def test_template_links(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = [rq.addon for rq in
                RereviewQueue.objects.all().order_by('created')]
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0], '1')),
            (unicode(apps[1].name), self.review_url(apps[1], '2')),
            (unicode(apps[2].name), self.review_url(apps[2], '3')),
        ]
        check_links(expected, links, verify=False)

    # TODO: Test actions buttons.
    # TODO: Test actions.

    def test_invalid_page(self):
        r = self.client.get(self.url, {'page': 999})
        eq_(r.status_code, 200)
        eq_(r.context['pager'].number, 1)

    def test_queue_count(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (3)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Escalations (0)')

    def test_redirect_to_review(self):
        r = self.client.get(self.url, {'num': 2})
        self.assertRedirects(r, self.review_url(self.apps[1], num=2))


class TestEscalationQueue(AppReviewerTest, AccessMixin):
    fixtures = ['base/devicetypes', 'base/users']

    def setUp(self):
        now = datetime.datetime.now()
        days_ago = lambda n: now - datetime.timedelta(days=n)

        self.apps = [app_factory(name='XXX'),
                     app_factory(name='YYY'),
                     app_factory(name='ZZZ')]

        eq1 = EscalationQueue.objects.create(addon=self.apps[0])
        eq1.update(created=days_ago(5))
        eq2 = EscalationQueue.objects.create(addon=self.apps[1])
        eq2.update(created=days_ago(3))
        eq3 = EscalationQueue.objects.create(addon=self.apps[2])
        eq3.update(created=days_ago(1))

        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_escalated')

    def review_url(self, app, num):
        return urlparams(reverse('reviewers.apps.review', args=[app.app_slug]),
                         num=num, tab='escalated')

    def test_template_links(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = [rq.addon for rq in
                EscalationQueue.objects.all().order_by('created')]
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0], '1')),
            (unicode(apps[1].name), self.review_url(apps[1], '2')),
            (unicode(apps[2].name), self.review_url(apps[2], '3')),
        ]
        check_links(expected, links, verify=False)

    def test_action_buttons(self):
        r = self.client.get(self.review_url(self.apps[0], '1'))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Clear Escalation', 'clear_escalation'),
            (u'Disable app', 'disable'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    # TODO: Test actions.

    def test_flag_info(self):
        self.apps[0].current_version.update(has_info_request=True)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(3)')
        flags = tds('div.ed-sprite-info')
        eq_(flags.length, 1)

    def test_flag_comment(self):
        self.apps[0].current_version.update(has_editor_comment=True)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(3)')
        flags = tds('div.ed-sprite-editor')
        eq_(flags.length, 1)

    def test_invalid_page(self):
        r = self.client.get(self.url, {'page': 999})
        eq_(r.status_code, 200)
        eq_(r.context['pager'].number, 1)

    def test_queue_count(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (0)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Escalations (3)')

    def test_redirect_to_review(self):
        r = self.client.get(self.url, {'num': 2})
        self.assertRedirects(r, self.review_url(self.apps[1], num=2))


class TestReviewApp(AppReviewerTest, AccessMixin):
    fixtures = ['base/platforms', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestReviewApp, self).setUp()
        self.app = self.get_app()
        self.mozilla_contact = 'contact@mozilla.com'
        self.app.update(status=amo.STATUS_PENDING,
                        mozilla_contact=self.mozilla_contact)
        self.version = self.app.current_version
        self.url = reverse('reviewers.apps.review', args=[self.app.app_slug])
        self.escalated_url = urlparams(
            reverse('reviewers.apps.review', args=[self.app.app_slug]),
            tab='escalated')

    def get_app(self):
        return Webapp.objects.get(id=337141)

    def post(self, data, url=None):
        r = self.client.post(url or self.url, data)
        # Purposefully not using assertRedirects to avoid having to mock ES.
        eq_(r.status_code, 302)
        ok_(reverse('reviewers.apps.queue_pending') in r['Location'])

    @mock.patch.object(settings, 'DEBUG', False)
    def test_cannot_review_my_app(self):
        AddonUser.objects.create(addon=self.app,
            user=UserProfile.objects.get(username='editor'))
        eq_(self.client.head(self.url).status_code, 302)

    def _check_email(self, msg, subject, with_mozilla_contact=True):
        eq_(msg.to, list(self.app.authors.values_list('email', flat=True)))
        if with_mozilla_contact:
            eq_(msg.cc, [self.mozilla_contact])
        else:
            eq_(msg.cc, [])
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

    def _check_score(self, reviewed_type):
        scores = ReviewerScore.objects.all()
        assert len(scores) > 0
        eq_(scores[0].score, amo.REVIEWED_SCORES[reviewed_type])
        eq_(scores[0].note_key, reviewed_type)

    def test_push_public(self):
        waffle.models.Switch.objects.create(name='reviewer-incentive-points',
                                            active=True)
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
        self._check_score(amo.REVIEWED_WEBAPP)

    def test_push_public_no_mozilla_contact(self):
        waffle.models.Switch.objects.create(name='reviewer-incentive-points',
                                            active=True)
        files = list(self.version.files.values_list('id', flat=True))
        self.app.update(mozilla_contact='')
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
        self._check_email(msg, 'App Approved', with_mozilla_contact=False)
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP)

    def test_push_public_waiting(self):
        waffle.models.Switch.objects.create(name='reviewer-incentive-points',
                                            active=True)
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
        self._check_score(amo.REVIEWED_WEBAPP)

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

    def test_clear_escalation(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        EscalationQueue.objects.create(addon=self.app)
        self.post({'action': 'clear_escalation', 'comments': 'all clear'},
                  url=self.escalated_url)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)
        self._check_log(amo.LOG.ESCALATION_CLEARED)
        # Ensure we don't send email on clearing escalations.
        eq_(len(mail.outbox), 0)

    def test_disable_app(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        EscalationQueue.objects.create(addon=self.app)
        self.post({'action': 'disable', 'comments': 'disabled ur app'},
                  url=self.escalated_url)
        eq_(EscalationQueue.objects.filter(addon=self.app).count(), 0)
        eq_(self.get_app().status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.APP_DISABLED)
        eq_(len(mail.outbox), 1)
        self._check_email(mail.outbox[0], 'App disabled by reviewer')

    def test_receipt_no_node(self):
        res = self.client.get(self.url)
        eq_(len(pq(res.content)('#receipt-check-result')), 0)

    def test_receipt_has_node(self):
        self.get_app().update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.get(self.url)
        eq_(len(pq(res.content)('#receipt-check-result')), 1)

    @mock.patch('mkt.reviewers.views.requests.get')
    def test_manifest_json(self, mock_get):
        m = mock.Mock()
        m.content = 'the manifest contents <script>'
        m.headers = {'content-type':
                     'application/x-web-app-manifest+json <script>'}
        mock_get.return_value = m

        expected = {
            'content': 'the manifest contents &lt;script&gt;',
            'headers': {'content-type':
                        'application/x-web-app-manifest+json &lt;script&gt;'}
        }

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        eq_(json.loads(r.content), expected)

    @mock.patch('mkt.reviewers.views.requests.get')
    def test_manifest_json_unicode(self, mock_get):
        m = mock.Mock()
        m.content = u'كك some foreign ish'
        m.headers = {}
        mock_get.return_value = m

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        eq_(json.loads(r.content), {'content': u'كك some foreign ish',
                                    'headers': {}})


class TestCannedResponses(AppReviewerTest):

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
        self.url = reverse('reviewers.apps.review', args=[self.app.app_slug])

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


class TestReviewLog(AppReviewerTest, AccessMixin):

    def setUp(self):
        self.login_as_editor()
        super(TestReviewLog, self).setUp()
        self.apps = [app_factory(name='XXX',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS),
                     app_factory(name='YYY',
                                 status=amo.WEBAPPS_UNREVIEWED_STATUS)]
        self.url = reverse('reviewers.apps.logs')

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

    def test_search_app_soft_deleted(self):
        self.make_approvals()
        self.apps[0].update(status=amo.STATUS_DELETED)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('#log-listing tbody tr').eq(0).attr('data-addonid'),
            str(self.apps[0].pk))

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


class TestMotd(AppReviewerTest, AccessMixin):

    def setUp(self):
        super(TestMotd, self).setUp()
        self.url = reverse('reviewers.apps.motd')
        self.key = u'mkt_reviewers_motd'
        set_config(self.key, u'original value')

    def test_perms_not_editor(self):
        self.client.logout()
        req = self.client.get(self.url, follow=True)
        self.assertRedirects(req, '%s?to=%s' % (reverse('users.login'),
                                                self.url))
        self.client.login(username='regular@mozilla.com',
                          password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_perms_not_motd(self):
        # Any type of reviewer can see the MOTD.
        self.login_as_editor()
        req = self.client.get(self.url)
        eq_(req.status_code, 200)
        eq_(req.context['form'], None)
        # No redirect means it didn't save.
        eq_(self.client.post(self.url, dict(motd='motd')).status_code, 200)
        eq_(get_config(self.key), u'original value')

    def test_motd_change(self):
        # Only users in the MOTD group can POST.
        user = UserProfile.objects.get(email='editor@mozilla.com')
        group = Group.objects.create(name='App Reviewer MOTD',
                                     rules='AppReviewerMOTD:Edit')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_editor()

        # Get is a 200 with a form.
        req = self.client.get(self.url)
        eq_(req.status_code, 200)
        eq_(req.context['form'].initial['motd'], u'original value')
        # Empty post throws an error.
        req = self.client.post(self.url, dict(motd=''))
        eq_(req.status_code, 200)  # Didn't redirect after save.
        eq_(pq(req.content)('#editor-motd .errorlist').text(),
            'This field is required.')
        # A real post now.
        req = self.client.post(self.url, dict(motd='new motd'))
        self.assertRedirects(req, self.url)
        eq_(get_config(self.key), u'new motd')
