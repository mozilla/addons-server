# -*- coding: utf-8 -*-
import datetime
import json
import time
from itertools import cycle

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.client import RequestFactory

import mock
from nose import SkipTest
from nose.tools import eq_, ok_
from pyquery import PyQuery as pq
import requests

import amo
import amo.tests
from abuse.models import AbuseReport
from access.models import GroupUser
from addons.models import AddonDeviceType, AddonUser, Persona
from amo.tests import (app_factory, addon_factory, check_links, days_ago,
                       formset, initial, version_factory)
from amo.urlresolvers import reverse
from amo.utils import isotime
from devhub.models import ActivityLog, AppLog
from editors.models import (CannedResponse, EscalationQueue, RereviewQueue,
                            ReviewerScore)
from files.models import File
from lib.crypto import packaged
from lib.crypto.tests import mock_sign
import mkt.constants.reviewers as rvw
from mkt.reviewers.models import ThemeLock
from mkt.reviewers.views import (_do_sort, _filter, _check_if_searching,
                                 _get_search_form, _get_themes, _queue_to_apps)
from mkt.site.fixtures import fixture
from mkt.submit.tests.test_views import BasePackagedAppTest
from mkt.webapps.models import Webapp
from mkt.webapps.tests.test_models import PackagedFilesMixin
import reviews
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from zadmin.models import get_config, set_config


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

    def login_as_senior_reviewer(self):
        self.client.logout()
        user = UserProfile.objects.get(email='editor@mozilla.com')
        self.grant_permission(user, 'Addons:Edit,Apps:ReviewEscalated')
        self.login_as_editor()

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


class SearchMixin(object):

    def test_search_query(self):
        # Light test to make sure queues can handle search queries.
        res = self.client.get(self.url, {'text_query': 'test'})
        eq_(res.status_code, 200)


class TestReviewersHome(AppReviewerTest, AccessMixin):

    def setUp(self):
        self.login_as_editor()
        super(TestReviewersHome, self).setUp()
        self.url = reverse('reviewers.home')
        self.apps = [app_factory(name='Antelope',
                                 status=amo.STATUS_PENDING),
                     app_factory(name='Bear',
                                 status=amo.STATUS_PENDING),
                     app_factory(name='Cougar',
                                 status=amo.STATUS_PENDING)]
        # Add a disabled app for good measure.
        app_factory(name='Dungeness Crab', disabled_by_user=True,
                    status=amo.STATUS_PENDING)
        # Escalate one app to make sure it doesn't affect stats.
        escalated = app_factory(name='Eyelash Pit Viper',
                                status=amo.STATUS_PENDING)
        EscalationQueue.objects.create(addon=escalated)

    def test_stats_waiting(self):
        self.apps[0].update(created=self.days_ago(1))
        self.apps[1].update(created=self.days_ago(5))
        self.apps[2].update(created=self.days_ago(15))

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


class FlagsMixin(object):

    def test_flag_packaged_app(self):
        self.apps[0].update(is_packaged=True)
        eq_(self.apps[0].is_packaged, True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        td = pq(res.content)('#addon-queue tbody tr td:nth-of-type(3)').eq(0)
        flag = td('div.sprite-reviewer-packaged-app')
        eq_(flag.length, 1)

    def test_flag_premium_app(self):
        self.apps[0].update(premium_type=amo.ADDON_PREMIUM)
        eq_(self.apps[0].is_premium(), True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td:nth-of-type(3)')
        flags = tds('div.sprite-reviewer-premium')
        eq_(flags.length, 1)

    def test_flag_info(self):
        self.apps[0].current_version.update(has_info_request=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td:nth-of-type(3)')
        flags = tds('div.sprite-reviewer-info')
        eq_(flags.length, 1)

    def test_flag_comment(self):
        self.apps[0].current_version.update(has_editor_comment=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td:nth-of-type(3)')
        flags = tds('div.sprite-reviewer-editor')
        eq_(flags.length, 1)


class XSSMixin(object):

    def test_xss_in_queue(self):
        a = self.apps[0]
        a.name = '<script>alert("xss")</script>'
        a.save()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tbody = pq(res.content)('#addon-queue tbody').html()
        assert '&lt;script&gt;' in tbody
        assert '<script>' not in tbody


class TestAppQueue(AppReviewerTest, AccessMixin, FlagsMixin, SearchMixin,
                   XSSMixin):
    fixtures = ['base/users']

    def setUp(self):
        self.apps = [app_factory(name='XXX',
                                 status=amo.STATUS_PENDING),
                     app_factory(name='YYY',
                                 status=amo.STATUS_PENDING),
                     app_factory(name='ZZZ')]
        self.apps[0].update(created=self.days_ago(2))
        self.apps[1].update(created=self.days_ago(1))

        RereviewQueue.objects.create(addon=self.apps[2])

        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_pending')

    def review_url(self, app):
        return reverse('reviewers.apps.review', args=[app.app_slug])

    def test_queue_viewing_ping(self):
        eq_(self.client.post(reverse('editors.queue_viewing')).status_code,
            200)

    def test_template_links(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = Webapp.objects.pending().order_by('created')
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0])),
            (unicode(apps[1].name), self.review_url(apps[1])),
        ]
        check_links(expected, links, verify=False)

    def test_action_buttons_pending(self):
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Reject', 'reject'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_action_buttons_rejected(self):
        # Check action buttons for a previously rejected app.
        self.apps[0].update(status=amo.STATUS_REJECTED)
        self.apps[0].latest_version.files.update(status=amo.STATUS_DISABLED)
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_devices(self):
        AddonDeviceType.objects.create(addon=self.apps[0], device_type=1)
        AddonDeviceType.objects.create(addon=self.apps[0], device_type=2)
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
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Moderated Reviews (0)')

    def test_queue_count_senior_reviewer(self):
        self.login_as_senior_reviewer()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (2)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (1)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (0)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')

    def test_escalated_not_in_queue(self):
        self.login_as_senior_reviewer()
        EscalationQueue.objects.create(addon=self.apps[0])
        res = self.client.get(self.url)
        # self.apps[2] is not pending so doesn't show up either.
        eq_([a.app for a in res.context['addons']], [self.apps[1]])

        doc = pq(res.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (1)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (1)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (1)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')


class TestRereviewQueue(AppReviewerTest, AccessMixin, FlagsMixin, SearchMixin,
                        XSSMixin):
    fixtures = ['base/users']

    def setUp(self):
        self.apps = [app_factory(name='XXX'),
                     app_factory(name='YYY'),
                     app_factory(name='ZZZ')]

        RereviewQueue.objects.create(addon=self.apps[0]).update(
            created=self.days_ago(5))
        RereviewQueue.objects.create(addon=self.apps[1]).update(
            created=self.days_ago(3))
        RereviewQueue.objects.create(addon=self.apps[2]).update(
            created=self.days_ago(1))
        self.apps[0].update(created=self.days_ago(5))
        self.apps[1].update(created=self.days_ago(3))
        self.apps[2].update(created=self.days_ago(1))

        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_rereview')

    def review_url(self, app):
        return reverse('reviewers.apps.review', args=[app.app_slug])

    def test_template_links(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = [rq.addon for rq in
                RereviewQueue.objects.all().order_by('created')]
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0])),
            (unicode(apps[1].name), self.review_url(apps[1])),
            (unicode(apps[2].name), self.review_url(apps[2])),
        ]
        check_links(expected, links, verify=False)

    def test_waiting_time(self):
        """Check objects show queue objects' created."""
        r = self.client.get(self.url)
        waiting_times = [wait.attrib['isotime'] for wait in
                         pq(r.content)('td time')]
        expected_waiting_times = [
            isotime(app.rereviewqueue_set.all()[0].created)
            for app in self.apps]
        self.assertSetEqual(expected_waiting_times, waiting_times)

    def test_action_buttons_public_senior_reviewer(self):
        self.login_as_senior_reviewer()

        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Reject', 'reject'),
            (u'Disable app', 'disable'),
            (u'Clear Re-review', 'clear_rereview'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_action_buttons_public(self):
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Reject', 'reject'),
            (u'Clear Re-review', 'clear_rereview'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_action_buttons_reject(self):
        self.apps[0].update(status=amo.STATUS_REJECTED)
        self.apps[0].latest_version.files.update(status=amo.STATUS_DISABLED)
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Clear Re-review', 'clear_rereview'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

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
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Moderated Reviews (0)')

    def test_queue_count_senior_reviewer(self):
        self.login_as_senior_reviewer()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (3)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (0)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')

    def test_escalated_not_in_queue(self):
        self.login_as_senior_reviewer()
        EscalationQueue.objects.create(addon=self.apps[0])
        res = self.client.get(self.url)
        self.assertSetEqual([a.app for a in res.context['addons']],
                            self.apps[1:])

        doc = pq(res.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (2)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (1)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')

    def test_addon_deleted(self):
        self.create_switch(name='soft_delete')
        app = self.apps[0]
        app.delete()
        eq_(RereviewQueue.objects.filter(addon=app).exists(), False)


class TestUpdateQueue(AppReviewerTest, AccessMixin, FlagsMixin, SearchMixin,
                      XSSMixin):
    fixtures = ['base/users']

    def setUp(self):
        app1 = app_factory(is_packaged=True, name='XXX',
                           version_kw={'version': '1.0',
                                       'created': self.days_ago(2)})
        app2 = app_factory(is_packaged=True, name='YYY',
                           version_kw={'version': '1.0',
                                       'created': self.days_ago(2)})

        version_factory(addon=app1, version='1.1', created=self.days_ago(1),
                        file_kw={'status': amo.STATUS_PENDING})
        version_factory(addon=app2, version='1.1', created=self.days_ago(1),
                        file_kw={'status': amo.STATUS_PENDING})

        self.apps = list(Webapp.objects.order_by('id'))
        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_updates')

    def review_url(self, app):
        return reverse('reviewers.apps.review', args=[app.app_slug])

    def test_template_links(self):
        self.apps[0].versions.latest().files.update(created=self.days_ago(2))
        self.apps[1].versions.latest().files.update(created=self.days_ago(1))
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        expected = [
            (unicode(self.apps[0].name), self.review_url(self.apps[0])),
            (unicode(self.apps[1].name), self.review_url(self.apps[1])),
        ]
        check_links(expected, links, verify=False)

    def test_action_buttons_public_senior_reviewer(self):
        self.apps[0].versions.latest().files.update(status=amo.STATUS_PUBLIC)
        self.login_as_senior_reviewer()

        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Reject', 'reject'),
            (u'Disable app', 'disable'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_action_buttons_public(self):
        self.apps[0].versions.latest().files.update(status=amo.STATUS_PUBLIC)

        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Reject', 'reject'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_action_buttons_reject(self):
        self.apps[0].versions.latest().files.update(status=amo.STATUS_DISABLED)

        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

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
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (2)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Moderated Reviews (0)')

    def test_queue_count_senior_reviewer(self):
        self.login_as_senior_reviewer()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (0)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (2)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (0)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')

    def test_escalated_not_in_queue(self):
        self.login_as_senior_reviewer()
        EscalationQueue.objects.create(addon=self.apps[0])
        res = self.client.get(self.url)
        eq_([a.app for a in res.context['addons']], self.apps[1:])

        doc = pq(res.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (0)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (1)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (1)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')

    def test_order(self):
        self.apps[0].update(created=self.days_ago(10))
        self.apps[1].update(created=self.days_ago(5))
        self.apps[0].versions.latest().files.update(created=self.days_ago(1))
        self.apps[1].versions.latest().files.update(created=self.days_ago(4))
        res = self.client.get(self.url)
        apps = list(res.context['addons'])
        eq_(apps[0].app, self.apps[1])
        eq_(apps[1].app, self.apps[0])

    def test_only_updates_in_queue(self):
        # Add new packaged app, which should only show up in the pending queue.
        app = app_factory(is_packaged=True, name='ZZZ',
                          status=amo.STATUS_PENDING,
                          version_kw={'version': '1.0'},
                          file_kw={'status': amo.STATUS_PENDING})
        res = self.client.get(self.url)
        apps = [a.app for a in res.context['addons']]
        assert app not in apps, (
            'Unexpected: Found a new packaged app in the updates queue.')
        eq_(pq(res.content)('.tabnav li a:eq(2)').text(), u'Updates (2)')


class TestEscalationQueue(AppReviewerTest, AccessMixin, FlagsMixin,
                          SearchMixin, XSSMixin):
    fixtures = ['base/users']

    def setUp(self):
        self.apps = [app_factory(name='XXX'),
                     app_factory(name='YYY'),
                     app_factory(name='ZZZ')]

        EscalationQueue.objects.create(addon=self.apps[0]).update(
            created=self.days_ago(5))
        EscalationQueue.objects.create(addon=self.apps[1]).update(
            created=self.days_ago(3))
        EscalationQueue.objects.create(addon=self.apps[2]).update(
            created=self.days_ago(1))
        self.apps[0].update(created=self.days_ago(5))
        self.apps[1].update(created=self.days_ago(3))
        self.apps[2].update(created=self.days_ago(1))

        self.login_as_senior_reviewer()
        self.url = reverse('reviewers.apps.queue_escalated')

    def review_url(self, app):
        return reverse('reviewers.apps.review', args=[app.app_slug])

    def test_flag_blocked(self):
        # Blocklisted apps should only be in the update queue, so this flag
        # check is here rather than in FlagsMixin.
        self.apps[0].update(status=amo.STATUS_BLOCKED)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td:nth-of-type(3)')
        flags = tds('div.sprite-reviewer-blocked')
        eq_(flags.length, 1)

    def test_no_access_regular_reviewer(self):
        # Since setUp added a new group, remove all groups and start over.
        user = UserProfile.objects.get(email='editor@mozilla.com')
        GroupUser.objects.filter(user=user).delete()
        self.grant_permission(user, 'Apps:Review')
        res = self.client.get(self.url)
        eq_(res.status_code, 403)

    def test_template_links(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(2) a')
        apps = [rq.addon for rq in
                EscalationQueue.objects.all().order_by('addon__created')]
        expected = [
            (unicode(apps[0].name), self.review_url(apps[0])),
            (unicode(apps[1].name), self.review_url(apps[1])),
            (unicode(apps[2].name), self.review_url(apps[2])),
        ]
        check_links(expected, links, verify=False)

    def test_waiting_time(self):
        """Check objects show queue objects' created."""
        r = self.client.get(self.url)
        waiting_times = [wait.attrib['isotime'] for wait in
                         pq(r.content)('td time')]
        expected_waiting_times = [
            isotime(app.escalationqueue_set.all()[0].created)
            for app in self.apps]
        self.assertSetEqual(expected_waiting_times, waiting_times)

    def test_action_buttons_public(self):
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Reject', 'reject'),
            (u'Disable app', 'disable'),
            (u'Clear Escalation', 'clear_escalation'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    def test_action_buttons_reject(self):
        self.apps[0].update(status=amo.STATUS_REJECTED)
        self.apps[0].latest_version.files.update(status=amo.STATUS_DISABLED)
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Disable app', 'disable'),
            (u'Clear Escalation', 'clear_escalation'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

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
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (3)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (0)')

    def test_abuse(self):
        AbuseReport.objects.create(addon=self.apps[0], message='!@#$')
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        tds = pq(r.content)('#addon-queue tbody')('tr td:nth-of-type(7)')
        eq_(tds.eq(0).text(), '1')

    def test_addon_deleted(self):
        self.create_switch(name='soft_delete')
        app = self.apps[0]
        app.delete()
        eq_(EscalationQueue.objects.filter(addon=app).exists(), False)


class TestReviewTransaction(amo.tests.test_utils.TransactionTestCase):
    fixtures = ['base/platforms', 'base/users', 'webapps/337141-steamcube']

    def get_app(self):
        return Webapp.uncached.get(id=337141)

    @mock.patch('lib.crypto.packaged.sign_app')
    def test_public_sign(self, sign):

        self.app = self.get_app()
        self.app.update(status=amo.STATUS_PENDING, is_packaged=True)
        self.version = self.app.current_version
        self.version.files.all().update(status=amo.STATUS_PENDING)
        eq_(self.get_app().status, amo.STATUS_PENDING)

        sign.return_value = None  # Didn't fail.
        self.client.login(username='editor@mozilla.com',
                          password='password')
        resp = self.client.post(
            reverse('reviewers.apps.review', args=[self.app.app_slug]),
            {'action': 'public', 'comments': 'something'})

        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(resp.status_code, 302)

    @mock.patch('lib.crypto.packaged.sign_app')
    def test_public_sign_failure(self, sign):

        self.app = self.get_app()
        self.app.update(status=amo.STATUS_PENDING, is_packaged=True)
        self.version = self.app.current_version
        self.version.files.all().update(status=amo.STATUS_PENDING)
        eq_(self.get_app().status, amo.STATUS_PENDING)

        sign.side_effect = packaged.SigningError('Bad things happened.')
        self.client.login(username='editor@mozilla.com',
                          password='password')
        resp = self.client.post(
            reverse('reviewers.apps.review', args=[self.app.app_slug]),
            {'action': 'public', 'comments': 'something'})

        eq_(self.get_app().status, amo.STATUS_PENDING)
        eq_(resp.status_code, 302)


class TestReviewApp(AppReviewerTest, AccessMixin, PackagedFilesMixin):
    fixtures = ['base/platforms', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestReviewApp, self).setUp()
        self.app = self.get_app()
        self.mozilla_contact = 'contact@mozilla.com'
        self.app.update(status=amo.STATUS_PENDING,
                        mozilla_contact=self.mozilla_contact)
        self.version = self.app.current_version
        self.version.files.all().update(status=amo.STATUS_PENDING)
        self.url = reverse('reviewers.apps.review', args=[self.app.app_slug])
        self.file = self.version.all_files[0]
        self.setup_files()

    def get_app(self):
        return Webapp.objects.get(id=337141)

    def post(self, data, queue='pending'):
        res = self.client.post(self.url, data)
        self.assert3xx(res, reverse('reviewers.apps.queue_%s' % queue))

    def test_review_viewing_ping(self):
        eq_(self.client.post(reverse('editors.review_viewing')).status_code,
            200)

    @mock.patch('mkt.webapps.models.Webapp.in_rereview_queue')
    def test_rereview(self, is_rereview_queue):
        is_rereview_queue.return_value = True
        content = pq(self.client.get(self.url).content)
        assert content('#queue-rereview').length

    @mock.patch('mkt.webapps.models.Webapp.in_escalation_queue')
    def test_escalated(self, in_escalation_queue):
        in_escalation_queue.return_value = True
        content = pq(self.client.get(self.url).content)
        assert content('#queue-escalation').length

    @mock.patch.object(settings, 'ALLOW_SELF_REVIEWS', False)
    def test_cannot_review_my_app(self):
        AddonUser.objects.create(
            addon=self.app, user=UserProfile.objects.get(username='editor'))
        res = self.client.head(self.url)
        self.assert3xx(res, reverse('reviewers.home'))
        res = self.client.post(self.url)
        self.assert3xx(res, reverse('reviewers.home'))

    def test_cannot_review_blocklisted_app(self):
        self.app.update(status=amo.STATUS_BLOCKED)
        res = self.client.get(self.url)
        self.assert3xx(res, reverse('reviewers.home'))
        res = self.client.post(self.url)
        self.assert3xx(res, reverse('reviewers.home'))

    def test_sr_can_review_blocklisted_app(self):
        self.app.update(status=amo.STATUS_BLOCKED)
        self.login_as_senior_reviewer()
        eq_(self.client.get(self.url).status_code, 200)
        res = self.client.post(self.url, {'action': 'public',
                                          'comments': 'yo'})
        self.assert3xx(res, reverse('reviewers.apps.queue_pending'))

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
        assert AppLog.objects.filter(
            addon=self.app, activity_log__action=action.id).exists(), (
                "Didn't find `%s` action in logs." % action.short)

    def _check_score(self, reviewed_type):
        scores = ReviewerScore.objects.all()
        assert len(scores) > 0
        eq_(scores[0].score, amo.REVIEWED_SCORES[reviewed_type])
        eq_(scores[0].note_key, reviewed_type)

    def test_xss(self):
        self.post({'action': 'comment',
                   'comments': '<script>alert("xss")</script>'})
        res = self.client.get(self.url)
        assert '<script>alert' not in res.content
        assert '&lt;script&gt;alert' in res.content

    def test_pending_to_public_w_device_overrides(self):
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_DESKTOP.id)
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_TABLET.id)
        eq_(self.app.make_public, amo.PUBLIC_IMMEDIATELY)
        self.post({
            'action': 'public',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
            'device_override': [amo.DEVICE_DESKTOP.id],
        })
        app = self.get_app()
        eq_(app.make_public, amo.PUBLIC_WAIT)
        eq_(app.status, amo.STATUS_PUBLIC_WAITING)
        eq_([o.id for o in app.device_types], [amo.DEVICE_DESKTOP.id])
        self._check_log(amo.LOG.REVIEW_DEVICE_OVERRIDE)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved but waiting')
        self._check_email_body(msg)

    def test_pending_to_reject_w_device_overrides(self):
        # This shouldn't be possible unless there's form hacking.
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_DESKTOP.id)
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_TABLET.id)
        eq_(self.app.make_public, amo.PUBLIC_IMMEDIATELY)
        self.post({
            'action': 'reject',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
            'device_override': [amo.DEVICE_DESKTOP.id],
        })
        app = self.get_app()
        eq_(app.make_public, amo.PUBLIC_IMMEDIATELY)
        eq_(app.status, amo.STATUS_REJECTED)
        eq_(set([o.id for o in app.device_types]),
            set([amo.DEVICE_DESKTOP.id, amo.DEVICE_TABLET.id]))

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)

    def test_pending_to_public(self):
        self.create_switch(name='reviewer-incentive-points')
        self.post({
            'action': 'public',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        })
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_PUBLIC)
        self._check_log(amo.LOG.APPROVE_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

    @mock.patch('mkt.webapps.models.Webapp.update_name_from_package_manifest')
    @mock.patch('lib.crypto.packaged.sign')
    def test_public_signs(self, sign, update):
        self.get_app().update(is_packaged=True)
        self.post({'action': 'public', 'comments': 'something'})

        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(sign.call_args[0][0], self.get_app().current_version.pk)
        assert update.called

    def test_pending_to_public_no_mozilla_contact(self):
        self.create_switch(name='reviewer-incentive-points')
        self.app.update(mozilla_contact='')
        self.post({
            'action': 'public',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        })
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_PUBLIC)
        self._check_log(amo.LOG.APPROVE_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved', with_mozilla_contact=False)
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

    def test_pending_to_public_waiting(self):
        self.create_switch(name='reviewer-incentive-points')
        self.get_app().update(make_public=amo.PUBLIC_WAIT)
        self.post({
            'action': 'public',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        })
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC_WAITING)
        eq_(app.current_version.files.all()[0].status,
            amo.STATUS_PUBLIC_WAITING)
        self._check_log(amo.LOG.APPROVE_VERSION_WAITING)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved but waiting')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

    @mock.patch('mkt.webapps.models.Webapp.update_name_from_package_manifest')
    @mock.patch('lib.crypto.packaged.sign')
    def test_public_waiting_signs(self, sign, update):
        self.get_app().update(is_packaged=True, make_public=amo.PUBLIC_WAIT)
        self.post({'action': 'public', 'comments': 'something'})

        eq_(self.get_app().status, amo.STATUS_PUBLIC_WAITING)
        eq_(sign.call_args[0][0], self.get_app().current_version.pk)
        assert not update.called

    def test_pending_to_reject(self):
        self.create_switch(name='reviewer-incentive-points')
        files = list(self.version.files.values_list('id', flat=True))
        self.post({'action': 'reject', 'comments': 'suxor'})
        app = self.get_app()
        eq_(app.status, amo.STATUS_REJECTED)
        eq_(File.objects.filter(id__in=files)[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.REJECT_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

    def test_multiple_versions_reject_hosted(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        self.app.current_version.files.update(status=amo.STATUS_PUBLIC)
        new_version = version_factory(addon=self.app)
        new_version.files.all().update(status=amo.STATUS_PENDING)
        self.post({
            'action': 'reject',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        })
        app = self.get_app()
        eq_(app.status, amo.STATUS_REJECTED)
        eq_(new_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.REJECT_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)

    def test_multiple_versions_reject_packaged(self):
        self.create_switch(name='reviewer-incentive-points')
        self.app.update(status=amo.STATUS_PUBLIC, is_packaged=True)
        self.app.current_version.files.update(status=amo.STATUS_PUBLIC)
        new_version = version_factory(addon=self.app)
        new_version.files.all().update(status=amo.STATUS_PENDING)
        self.post({
            'action': 'reject',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        })
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(new_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.REJECT_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_UPDATE)

    def test_pending_to_escalation(self):
        self.post({'action': 'escalate', 'comments': 'soup her man'})
        eq_(EscalationQueue.objects.count(), 1)
        self._check_log(amo.LOG.ESCALATE_MANUAL)
        # Test 2 emails: 1 to dev, 1 to admin.
        eq_(len(mail.outbox), 2)
        dev_msg = mail.outbox[0]
        self._check_email(dev_msg, 'Submission Update')
        adm_msg = mail.outbox[1]
        self._check_admin_email(adm_msg, 'Escalated Review Requested')

    def test_pending_to_disable_senior_reviewer(self):
        self.login_as_senior_reviewer()

        self.app.update(status=amo.STATUS_PUBLIC)
        self.post({'action': 'disable', 'comments': 'disabled ur app'})
        app = self.get_app()
        eq_(app.status, amo.STATUS_DISABLED)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.APP_DISABLED)
        eq_(len(mail.outbox), 1)
        self._check_email(mail.outbox[0], 'App disabled by reviewer')

    def test_pending_to_disable(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        res = self.client.post(self.url, {'action': 'disable',
                                          'comments': 'disabled ur app'})
        eq_(res.status_code, 200)
        ok_('action' in res.context['form'].errors)
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(len(mail.outbox), 0)

    def test_escalation_to_public(self):
        EscalationQueue.objects.create(addon=self.app)
        eq_(self.app.status, amo.STATUS_PENDING)
        self.post({
            'action': 'public',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        }, queue='escalated')
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_PUBLIC)
        self._check_log(amo.LOG.APPROVE_VERSION)
        eq_(EscalationQueue.objects.count(), 0)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved')
        self._check_email_body(msg)

    def test_escalation_to_reject(self):
        self.create_switch(name='reviewer-incentive-points')
        EscalationQueue.objects.create(addon=self.app)
        eq_(self.app.status, amo.STATUS_PENDING)
        files = list(self.version.files.values_list('id', flat=True))
        self.post({
            'action': 'reject',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        }, queue='escalated')
        app = self.get_app()
        eq_(app.status, amo.STATUS_REJECTED)
        eq_(File.objects.filter(id__in=files)[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.REJECT_VERSION)
        eq_(EscalationQueue.objects.count(), 0)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

    def test_escalation_to_disable_senior_reviewer(self):
        self.login_as_senior_reviewer()

        EscalationQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        self.post({'action': 'disable', 'comments': 'disabled ur app'},
                  queue='escalated')
        app = self.get_app()
        eq_(app.status, amo.STATUS_DISABLED)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.APP_DISABLED)
        eq_(EscalationQueue.objects.count(), 0)
        eq_(len(mail.outbox), 1)
        self._check_email(mail.outbox[0], 'App disabled by reviewer')

    def test_escalation_to_disable(self):
        EscalationQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        res = self.client.post(self.url, {'action': 'disable',
                                          'comments': 'disabled ur app'},
                               queue='escalated')
        eq_(res.status_code, 200)
        ok_('action' in res.context['form'].errors)
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(EscalationQueue.objects.count(), 1)
        eq_(len(mail.outbox), 0)

    def test_clear_escalation(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        EscalationQueue.objects.create(addon=self.app)
        self.post({'action': 'clear_escalation', 'comments': 'all clear'},
                  queue='escalated')
        eq_(EscalationQueue.objects.count(), 0)
        self._check_log(amo.LOG.ESCALATION_CLEARED)
        # Ensure we don't send email on clearing escalations.
        eq_(len(mail.outbox), 0)

    def test_rereview_to_reject(self):
        self.create_switch(name='reviewer-incentive-points')
        RereviewQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        self.post({
            'action': 'reject',
            'device_types': '',
            'browsers': '',
            'comments': 'something',
        }, queue='rereview')
        eq_(self.get_app().status, amo.STATUS_REJECTED)
        self._check_log(amo.LOG.REJECT_VERSION)
        eq_(RereviewQueue.objects.count(), 0)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_REREVIEW)

    def test_rereview_to_disable_senior_reviewer(self):
        self.login_as_senior_reviewer()

        RereviewQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        self.post({'action': 'disable', 'comments': 'disabled ur app'},
                  queue='rereview')
        eq_(self.get_app().status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.APP_DISABLED)
        eq_(RereviewQueue.objects.filter(addon=self.app).count(), 0)
        eq_(len(mail.outbox), 1)
        self._check_email(mail.outbox[0], 'App disabled by reviewer')

    def test_rereview_to_disable(self):
        RereviewQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        res = self.client.post(self.url, {'action': 'disable',
                                          'comments': 'disabled ur app'},
                               queue='rereview')
        eq_(res.status_code, 200)
        ok_('action' in res.context['form'].errors)
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(RereviewQueue.objects.filter(addon=self.app).count(), 1)
        eq_(len(mail.outbox), 0)

    def test_clear_rereview(self):
        self.create_switch(name='reviewer-incentive-points')
        self.app.update(status=amo.STATUS_PUBLIC)
        RereviewQueue.objects.create(addon=self.app)
        self.post({'action': 'clear_rereview', 'comments': 'all clear'},
                  queue='rereview')
        eq_(RereviewQueue.objects.count(), 0)
        self._check_log(amo.LOG.REREVIEW_CLEARED)
        # Ensure we don't send email on clearing re-reviews..
        eq_(len(mail.outbox), 0)
        self._check_score(amo.REVIEWED_WEBAPP_REREVIEW)

    def test_rereview_to_escalation(self):
        RereviewQueue.objects.create(addon=self.app)
        self.post({'action': 'escalate', 'comments': 'soup her man'},
                  queue='rereview')
        eq_(EscalationQueue.objects.count(), 1)
        self._check_log(amo.LOG.ESCALATE_MANUAL)
        # Test 2 emails: 1 to dev, 1 to admin.
        eq_(len(mail.outbox), 2)
        dev_msg = mail.outbox[0]
        self._check_email(dev_msg, 'Submission Update')
        adm_msg = mail.outbox[1]
        self._check_admin_email(adm_msg, 'Escalated Review Requested')

    def test_more_information(self):
        # Test the same for all queues.
        self.post({'action': 'info', 'comments': 'Knead moor in faux'})
        eq_(self.get_app().status, amo.STATUS_PENDING)
        self._check_log(amo.LOG.REQUEST_INFORMATION)
        vqs = self.get_app().versions.all()
        eq_(vqs.count(), 1)
        eq_(vqs.filter(has_info_request=True).count(), 1)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')

    def test_comment(self):
        # Test the same for all queues.
        self.post({'action': 'comment', 'comments': 'mmm, nice app'})
        eq_(len(mail.outbox), 0)
        self._check_log(amo.LOG.COMMENT_VERSION)

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
                        'application/x-web-app-manifest+json &lt;script&gt;'},
            'success': True,
            'permissions': {}
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
                                    'headers': {}, 'success': True,
                                    'permissions': {}})

    @mock.patch('mkt.reviewers.views.requests.get')
    def test_manifest_json_encoding(self, mock_get):
        m = mock.Mock()
        with storage.open(self.manifest_path('non-utf8.webapp')) as fp:
            m.content = fp.read()
        m.headers = {}
        mock_get.return_value = m

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert u'"name": "W2MO\u017d"' in data['content']

    @mock.patch('mkt.reviewers.views.requests.get')
    def test_manifest_json_encoding_empty(self, mock_get):
        m = mock.Mock()
        m.content = ''
        m.headers = {}
        mock_get.return_value = m

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        eq_(json.loads(r.content), {'content': u'', 'headers': {},
                                    'success': True, 'permissions': {}})

    @mock.patch('mkt.reviewers.views.requests.get')
    def test_manifest_json_traceback_in_response(self, mock_get):
        m = mock.Mock()
        m.content = {'name': 'Some name'}
        m.headers = {}
        mock_get.side_effect = requests.exceptions.SSLError
        mock_get.return_value = m

        # We should not 500 on a traceback.

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert data['content'], 'There should be a content with the traceback'
        eq_(data['headers'], {})

    @mock.patch('mkt.reviewers.views._mini_manifest')
    def test_manifest_json_packaged(self, mock_):
        # Test that when the app is packaged, _mini_manifest is called.
        mock_.return_value = '{}'

        self.get_app().update(is_packaged=True)
        res = self.client.get(reverse('reviewers.apps.review.manifest',
                                      args=[self.app.app_slug]))
        eq_(res.status_code, 200)
        assert mock_.called

    @mock.patch('mkt.reviewers.views.requests.get')
    def test_manifest_json_perms(self, mock_get):
        m = mock.Mock()
        m.content = """
        {"permissions":
            {"foo": {"description": "foo"},
             "camera": {"description": "<script>"}
            }
        }
        """
        m.headers = {'content-type':
                     'application/x-web-app-manifest+json <script>'}
        mock_get.return_value = m

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        eq_(json.loads(r.content)['permissions'],
            {'foo': {'description': 'foo', 'type': 'web'},
             'camera': {'description': '&lt;script&gt;', 'type': 'cert'}})

    def test_abuse(self):
        AbuseReport.objects.create(addon=self.app, message='!@#$')
        res = self.client.get(self.url)
        doc = pq(res.content)
        dd = doc('#summary dd.abuse-reports')
        eq_(dd.text(), u'1')
        eq_(dd.find('a').attr('href'), reverse('reviewers.apps.review.abuse',
                                               args=[self.app.app_slug]))


class TestCannedResponses(AppReviewerTest):

    def setUp(self):
        super(TestCannedResponses, self).setUp()
        self.login_as_editor()
        self.app = app_factory(name='XXX',
                               status=amo.STATUS_PENDING)
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
        # Note: if `created` is not specified, `addon_factory`/`app_factory`
        # uses a randomly generated timestamp.
        self.apps = [app_factory(name='XXX', created=days_ago(3),
                                 status=amo.STATUS_PENDING),
                     app_factory(name='YYY', created=days_ago(2),
                                 status=amo.STATUS_PENDING)]
        self.url = reverse('reviewers.apps.logs')

        self.task_user = UserProfile.objects.get(email='admin@mozilla.com')
        patcher = mock.patch.object(settings, 'TASK_USER_ID',
                                    self.task_user.id)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_user(self):
        return UserProfile.objects.all()[0]

    def make_approvals(self):
        for app in self.apps:
            amo.log(amo.LOG.REJECT_VERSION, app, app.current_version,
                    user=self.get_user(), details={'comments': 'youwin'})
            # Throw in a few tasks logs that shouldn't get queried.
            amo.log(amo.LOG.REREVIEW_MANIFEST_CHANGE, app, app.current_version,
                    user=self.task_user, details={'comments': 'foo'})

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
        all_reviews = [d.attrib.get('data-addonid')
                       for d in doc('#log-listing tbody tr')]
        assert str(self.apps[0].pk) in all_reviews, (
            'Soft deleted review did not show up in listing')

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
        self.make_an_approval(amo.LOG.ESCALATE_MANUAL, comment='hello')
        r = self.client.get(self.url, dict(search='hello'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#log-listing tbody tr.hide').eq(0).text(), 'hello')

    def test_search_comment_doesnt_exist(self):
        """Search by comment, with no results."""
        self.make_an_approval(amo.LOG.ESCALATE_MANUAL, comment='hello')
        r = self.client.get(self.url, dict(search='bye'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    def test_search_author_exists(self):
        """Search by author."""
        self.make_approvals()
        self.make_an_approval(amo.LOG.ESCALATE_MANUAL, username='editor',
                              comment='hi')

        r = self.client.get(self.url, dict(search='editor'))
        eq_(r.status_code, 200)
        rows = pq(r.content)('#log-listing tbody tr')

        eq_(rows.filter(':not(.hide)').length, 1)
        eq_(rows.filter('.hide').eq(0).text(), 'hi')

    def test_search_author_doesnt_exist(self):
        """Search by author, with no results."""
        self.make_approvals()
        self.make_an_approval(amo.LOG.ESCALATE_MANUAL, username='editor')

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

    def test_escalate_logs(self):
        self.make_an_approval(amo.LOG.ESCALATE_MANUAL)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td a').eq(1).text(),
            'Reviewer escalation')

    def test_no_double_encode(self):
        version = self.apps[0].current_version
        version.update(version='<foo>')
        self.make_an_approval(amo.LOG.ESCALATE_MANUAL)
        r = self.client.get(self.url)
        assert '<foo>' in pq(r.content)('#log-listing tr td').eq(1).text(), (
            'Double-encoded string was found in reviewer log.')


class TestMotd(AppReviewerTest, AccessMixin):

    def setUp(self):
        super(TestMotd, self).setUp()
        self.url = reverse('reviewers.apps.motd')
        self.key = u'mkt_reviewers_motd'
        set_config(self.key, u'original value')

    def test_perms_not_editor(self):
        self.client.logout()
        req = self.client.get(self.url, follow=True)
        self.assert3xx(req, '%s?to=%s' % (reverse('users.login'), self.url))
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
        self.grant_permission(user, 'AppReviewerMOTD:Edit')
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
        self.assert3xx(req, self.url)
        eq_(get_config(self.key), u'new motd')


class TestAbuseReports(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        user = UserProfile.objects.all()[0]
        self.app = app_factory()
        AbuseReport.objects.create(addon_id=self.app.id, message='eff')
        AbuseReport.objects.create(addon_id=self.app.id, message='yeah',
                                   reporter=user)
        # Make a user abuse report to make sure it doesn't show up.
        AbuseReport.objects.create(user=user, message='hey now')

    def test_abuse_reports_list(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('reviewers.apps.review.abuse',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        # We see the two abuse reports created in setUp.
        reports = r.context['reports']
        eq_(len(reports), 2)
        eq_(sorted([r.message for r in reports]), [u'eff', u'yeah'])


class TestModeratedQueue(AppReviewerTest, AccessMixin):
    fixtures = ['base/users']

    def setUp(self):
        self.app = app_factory()

        self.reviewer = UserProfile.objects.get(email='editor@mozilla.com')
        self.users = list(UserProfile.objects.exclude(pk=self.reviewer.id))

        self.url = reverse('reviewers.apps.queue_moderated')

        self.review1 = Review.objects.create(addon=self.app, body='body',
                                             user=self.users[0], rating=3,
                                             editorreview=True)
        ReviewFlag.objects.create(review=self.review1, flag=ReviewFlag.SPAM,
                                  user=self.users[0])
        self.review2 = Review.objects.create(addon=self.app, body='body',
                                             user=self.users[1], rating=4,
                                             editorreview=True)
        ReviewFlag.objects.create(review=self.review2, flag=ReviewFlag.SUPPORT,
                                  user=self.users[1])

        self.client.login(username=self.reviewer.email, password='password')

    def _post(self, action):
        ctx = self.client.get(self.url).context
        data_formset = formset(initial(ctx['reviews_formset'].forms[0]))
        data_formset['form-0-action'] = action

        res = self.client.post(self.url, data_formset)
        self.assert3xx(res, self.url)

    def _get_logs(self, action):
        return ActivityLog.objects.filter(action=action.id)

    def test_setup(self):
        eq_(Review.objects.filter(editorreview=True).count(), 2)
        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.SPAM).count(), 1)

        res = self.client.get(self.url)
        doc = pq(res.content)('#reviews-flagged')

        # Test the default action is "skip".
        eq_(doc('#id_form-0-action_1:checked').length, 1)

    def test_skip(self):
        # Skip the first review, which still leaves two.
        self._post(reviews.REVIEW_MODERATE_SKIP)
        res = self.client.get(self.url)
        eq_(len(res.context['page'].object_list), 2)

    def test_delete(self):
        # Delete the first review, which leaves one.
        self._post(reviews.REVIEW_MODERATE_DELETE)
        res = self.client.get(self.url)
        eq_(len(res.context['page'].object_list), 1)
        eq_(self._get_logs(amo.LOG.DELETE_REVIEW).count(), 1)

    def test_keep(self):
        # Keep the first review, which leaves one.
        self._post(reviews.REVIEW_MODERATE_KEEP)
        res = self.client.get(self.url)
        eq_(len(res.context['page'].object_list), 1)
        eq_(self._get_logs(amo.LOG.APPROVE_REVIEW).count(), 1)

    def test_no_reviews(self):
        Review.objects.all().delete()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(pq(res.content)('#reviews-flagged .no-results').length, 1)

    def test_queue_count(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (0)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Moderated Reviews (2)')

    def test_queue_count_senior_reviewer(self):
        self.login_as_senior_reviewer()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Apps (0)')
        eq_(doc('.tabnav li a:eq(1)').text(), u'Re-reviews (0)')
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (0)')
        eq_(doc('.tabnav li a:eq(3)').text(), u'Escalations (0)')
        eq_(doc('.tabnav li a:eq(4)').text(), u'Moderated Reviews (2)')


class TestThemeReviewQueue(amo.tests.TestCase):
    fixtures = ['base/users', 'base/admin']

    def setUp(self):
        self.reviewer_count = 0
        self.create_switch(name='mkt-themes')

    def create_and_become_reviewer(self):
        """Login as new reviewer with unique username."""
        username = 'reviewer%s' % self.reviewer_count
        email = username + '@mozilla.com'
        reviewer = User.objects.create(username=email, email=email,
                                       is_active=True, is_superuser=True)
        user = UserProfile.objects.create(user=reviewer, email=email,
                                          username=username)
        user.set_password('password')
        user.save()
        GroupUser.objects.create(group_id=50002, user=user)

        self.client.login(username=email, password='password')
        self.reviewer_count += 1
        return user

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_basic_queue(self):
        """
        Have reviewers take themes from the pool,
        check their queue sizes.
        """
        for x in range(rvw.THEME_INITIAL_LOCKS + 1):
            addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)

        themes = Persona.objects.all()
        expected_themes = [
            [themes[0], themes[1]],
            [themes[2]],
            []
        ]

        for expected in expected_themes:
            reviewer = self.create_and_become_reviewer()
            eq_(_get_themes(reviewer, initial=False), expected)
            eq_(ThemeLock.objects.filter(reviewer=reviewer).count(),
                len(expected))

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_more(self):
        """
        Test number of themes checked out when asking for more
        asynchronously.
        """
        for x in range(rvw.THEME_INITIAL_LOCKS + 1):
            addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)

        themes = Persona.objects.all()
        expected_themes = [
            [themes[0], themes[1]],
            [themes[2]],
            []
        ]

        reviewer = self.create_and_become_reviewer()
        for expected in expected_themes:
            eq_(_get_themes(reviewer, initial=False), expected)

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_top_off(self):
        """If reviewer has fewer than max locks, get more from pool."""
        for x in range(2):
            addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)
        reviewer = self.create_and_become_reviewer()
        _get_themes(reviewer, initial=True)
        ThemeLock.objects.filter(reviewer=reviewer)[0].delete()
        _get_themes(reviewer, initial=True)

        # Check reviewer checked out the themes.
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(),
            rvw.THEME_INITIAL_LOCKS)

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_expiry(self):
        """
        Test that reviewers who want themes from an empty pool can steal
        checked-out themes from other reviewers whose locks have expired.
        """
        for x in range(2):
            addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)
        reviewer = self.create_and_become_reviewer()
        _get_themes(reviewer, initial=True)

        # Reviewer wants themes, but empty pool.
        reviewer = self.create_and_become_reviewer()
        _get_themes(reviewer, initial=True)
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(), 0)

        # Manually expire a lock and see if it's reassigned.
        expired_theme_lock = ThemeLock.objects.all()[0]
        expired_theme_lock.expiry = datetime.datetime.now()
        expired_theme_lock.save()
        _get_themes(reviewer, initial=True)
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(), 1)

    def test_expiry_update(self):
        """Test expiry is updated when reviewer reloads his queue."""
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)
        reviewer = self.create_and_become_reviewer()
        _get_themes(reviewer, initial=True)

        earlier = datetime.datetime.now() - datetime.timedelta(minutes=10)
        ThemeLock.objects.filter(reviewer=reviewer).update(expiry=earlier)
        _get_themes(reviewer, initial=True)
        eq_(ThemeLock.objects.filter(reviewer=reviewer)[0].expiry > earlier,
            True)

    def test_permissions_reviewer(self):
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)
        slug = Persona.objects.all()[0].addon.slug

        res = self.client.get(reverse('reviewers.themes.queue_themes'))
        self.assert3xx(res, reverse('users.login') + '?to=' +
                       reverse('reviewers.themes.queue_themes'))

        self.client.login(username='regular@mozilla.com', password='password')

        eq_(self.client.get(reverse('reviewers.themes.queue_themes'))
            .status_code, 403)
        eq_(self.client.get(reverse('reviewers.themes.single',
                            args=[slug])).status_code, 403)
        eq_(self.client.post(reverse('reviewers.themes.commit')).status_code,
            403)
        eq_(self.client.get(reverse('reviewers.themes.more')).status_code, 403)

        self.create_and_become_reviewer()

        eq_(self.client.get(reverse('reviewers.themes.queue_themes'))
            .status_code, 200)
        eq_(self.client.get(reverse('reviewers.themes.single',
                            args=[slug])).status_code, 200)
        eq_(self.client.get(reverse('reviewers.themes.commit')).status_code,
            405)
        eq_(self.client.get(reverse('reviewers.themes.more')).status_code, 200)

    def test_commit(self):
        for x in range(5):
            addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)

        count = Persona.objects.count()
        form_data = amo.tests.formset(initial_count=count,
                                      total_count=count + 1)
        themes = Persona.objects.all()

        # Create locks.
        reviewer = self.create_and_become_reviewer()
        for index, theme in enumerate(themes):
            ThemeLock.objects.create(
                theme=theme, reviewer=reviewer,
                expiry=datetime.datetime.now() +
                datetime.timedelta(minutes=rvw.THEME_LOCK_EXPIRY))
            form_data['form-%s-theme' % index] = str(theme.id)

        # moreinfo
        form_data['form-%s-action' % 0] = str(rvw.ACTION_MOREINFO)
        form_data['form-%s-comment' % 0] = 'moreinfo'
        form_data['form-%s-reject_reason' % 0] = ''

        # flag
        form_data['form-%s-action' % 1] = str(rvw.ACTION_FLAG)
        form_data['form-%s-comment' % 1] = 'flag'
        form_data['form-%s-reject_reason' % 1] = ''

        # duplicate
        form_data['form-%s-action' % 2] = str(rvw.ACTION_DUPLICATE)
        form_data['form-%s-comment' % 2] = 'duplicate'
        form_data['form-%s-reject_reason' % 2] = ''

        # reject (other)
        form_data['form-%s-action' % 3] = str(rvw.ACTION_REJECT)
        form_data['form-%s-comment' % 3] = 'reject'
        form_data['form-%s-reject_reason' % 3] = '0'

        # approve
        form_data['form-%s-action' % 4] = str(rvw.ACTION_APPROVE)
        form_data['form-%s-comment' % 4] = ''
        form_data['form-%s-reject_reason' % 4] = ''

        res = self.client.post(reverse('reviewers.themes.commit'), form_data)
        self.assert3xx(res, reverse('reviewers.themes.queue_themes'))

        eq_(themes[0].addon.status, amo.STATUS_REVIEW_PENDING)
        eq_(themes[1].addon.status, amo.STATUS_REVIEW_PENDING)
        eq_(themes[2].addon.status, amo.STATUS_REJECTED)
        eq_(themes[3].addon.status, amo.STATUS_REJECTED)
        eq_(themes[4].addon.status, amo.STATUS_PUBLIC)
        eq_(ActivityLog.objects.count(), 5)

    def test_user_review_history(self):
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)

        reviewer = self.create_and_become_reviewer()

        res = self.client.get(reverse('reviewers.themes.history'))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('tbody tr').length, 0)

        theme = Persona.objects.all()[0]
        for x in range(3):
            amo.log(amo.LOG.THEME_REVIEW, theme.addon, user=reviewer,
                    details={'action': rvw.ACTION_APPROVE,
                             'comment': '', 'reject_reason': ''})

        res = self.client.get(reverse('reviewers.themes.history'))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('tbody tr').length, 3)

        res = self.client.get(reverse('reviewers.themes.logs'))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('tbody tr').length, 3 * 2)  # Double for comment rows.

    def test_single_basic(self):
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)

        self.create_and_become_reviewer()
        res = self.client.get(reverse('reviewers.themes.single',
                              args=[Persona.objects.all()[0].addon.slug]))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('.theme').length, 1)


class TestGetSigned(BasePackagedAppTest, amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_editor',
                       'user_editor_group', 'group_editor')

    def setUp(self):
        super(TestGetSigned, self).setUp()
        self.url = reverse('reviewers.signed', args=[self.app.app_slug,
                                                     self.version.pk])
        self.client.login(username='editor@mozilla.com', password='password')

    def test_not_logged_in(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_not_reviewer(self):
        self.client.logout()
        self.client.login(username='regular@mozilla.com', password='password')
        eq_(self.client.get(self.url).status_code, 403)

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_reviewer(self):
        if not settings.XSENDFILE:
            raise SkipTest()

        self.setup_files()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        file_ = self.app.current_version.all_files[0]
        eq_(res['x-sendfile'], file_.signed_reviewer_file_path)
        eq_(res['etag'], '"%s"' % file_.hash.split(':')[-1])

    def test_not_packaged(self):
        self.app.update(is_packaged=False)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_wrong_version(self):
        self.url = reverse('reviewers.signed', args=[self.app.app_slug, 0])
        res = self.client.get(self.url)
        eq_(res.status_code, 404)


class TestMiniManifestView(BasePackagedAppTest):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestMiniManifestView, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        self.version = self.app.versions.latest()
        self.file = self.version.all_files[0]
        self.file.update(filename='mozball.zip')
        self.url = reverse('reviewers.mini_manifest', args=[self.app.id,
                                                            self.version.pk])
        self.client.login(username='editor@mozilla.com', password='password')

    def test_not_logged_in(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_not_reviewer(self):
        self.client.logout()
        self.client.login(username='regular@mozilla.com', password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_not_packaged(self):
        self.app.update(is_packaged=False)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_wrong_version(self):
        url = reverse('reviewers.mini_manifest', args=[self.app.id, 0])
        res = self.client.get(url)
        eq_(res.status_code, 404)

    def test_reviewer(self):
        self.setup_files()
        res = self.client.get(self.url)
        eq_(res['Content-type'], 'application/x-web-app-manifest+json')
        data = json.loads(res.content)
        eq_(data['name'], self.app.name)
        eq_(data['developer']['name'], 'Mozilla Labs')
        eq_(data['package_path'], reverse('reviewers.signed',
                                          args=[self.app.app_slug,
                                                self.version.id]))

    def test_rejected(self):
        # Rejected sets file.status to DISABLED and moves to a guarded path.
        self.setup_files()
        self.app.update(status=amo.STATUS_REJECTED)
        self.file.update(status=amo.STATUS_DISABLED)
        res = self.client.get(self.url)
        eq_(res['Content-type'], 'application/x-web-app-manifest+json')
        data = json.loads(res.content)
        eq_(data['name'], self.app.name)
        eq_(data['developer']['name'], 'Mozilla Labs')
        eq_(data['package_path'], reverse('reviewers.signed',
                                          args=[self.app.app_slug,
                                                self.version.id]))


class TestReviewersScores(AppReviewerTest, AccessMixin):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReviewersScores, self).setUp()
        self.login_as_editor()
        self.user = UserProfile.objects.get(email='editor@mozilla.com')
        self.url = reverse('reviewers.performance', args=[self.user.username])

    def test_404(self):
        res = self.client.get(reverse('reviewers.performance', args=['poop']))
        eq_(res.status_code, 404)

    def test_with_username(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res.context['profile'].id, self.user.id)

    def test_without_username(self):
        res = self.client.get(reverse('reviewers.performance'))
        eq_(res.status_code, 200)
        eq_(res.context['profile'].id, self.user.id)

    def test_no_reviews(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert u'No review points awarded yet' in res.content


class TestQueueSearchSort(AppReviewerTest):
    fixtures = ['base/users']

    def setUp(self):
        """Create and set up apps for some filtering fun."""
        self.rf = RequestFactory()

        self.login_as_senior_reviewer()
        self.apps = [app_factory(name='Lillard',
                                 status=amo.STATUS_PENDING,
                                 is_packaged=False,
                                 version_kw={'version': '1.0'},
                                 admin_review=True,
                                 premium_type=amo.ADDON_FREE),
                     app_factory(name='Batum',
                                 status=amo.STATUS_PENDING,
                                 is_packaged=True,
                                 version_kw={'version': '1.0',
                                             'has_editor_comment': True,
                                             'has_info_request': True},
                                 admin_review=False,
                                 premium_type=amo.ADDON_PREMIUM)]

        # Set up app attributes.
        self.apps[0].update(created=self.days_ago(2))
        self.apps[1].update(created=self.days_ago(5))
        self.apps[0].addonuser_set.create(
            user=UserProfile.objects.create(username='XXX', email='XXX'))
        self.apps[1].addonuser_set.create(
            user=UserProfile.objects.create(username='illmatic',
                                            email='brandon@roy.com'))
        self.apps[0].addondevicetype_set.create(
            device_type=amo.DEVICE_DESKTOP.id)
        self.apps[1].addondevicetype_set.create(
            device_type=amo.DEVICE_MOBILE.id)

        self.url = reverse('reviewers.apps.queue_pending')

    def test_filter(self):
        """For each field in the form, run it through view and check results.
        """
        both_apps = (self.apps[0].id, self.apps[1].id)
        app0 = (self.apps[0].id,)
        app1 = (self.apps[1].id,)

        self.do_filter(app1, text_query='roy')
        self.do_filter(both_apps, text_query='illa atu')
        self.do_filter(both_apps, text_query='ill')

        self.do_filter(both_apps, admin_review=False)
        self.do_filter(app0, admin_review=True)

        self.do_filter(both_apps, has_editor_comment=False)
        self.do_filter(app1, has_editor_comment=True)

        self.do_filter(both_apps, has_info_request=False)
        self.do_filter(app1, has_info_request=True)

        self.do_filter(both_apps, waiting_time_days=1)
        self.do_filter(app1, waiting_time_days=4)

        self.do_filter(app0, app_type=rvw.APP_TYPE_HOSTED)
        self.do_filter(app1, app_type=rvw.APP_TYPE_PACKAGED)

        self.do_filter(both_apps, device_type_ids=[amo.DEVICE_MOBILE.id,
                                                   amo.DEVICE_DESKTOP.id])
        self.do_filter(app0, device_type_ids=[amo.DEVICE_DESKTOP.id])
        self.do_filter(app1, device_type_ids=[amo.DEVICE_MOBILE.id])

        self.do_filter(both_apps, premium_type_ids=[amo.ADDON_FREE,
                                                    amo.ADDON_PREMIUM])
        self.do_filter(app0, premium_type_ids=[amo.ADDON_FREE])
        self.do_filter(app1, premium_type_ids=[amo.ADDON_PREMIUM])

    def do_filter(self, expected_ids, **kw):
        """Checks that filter returns the expected ids

        expected_ids -- list of app ids expected in the result.
        """
        qs = _filter(Webapp.objects.all(), kw)

        self.assertSetEqual(qs.values_list('id', flat=True), expected_ids)

    def test_no_duplicate_locale(self):
        """
        Test that filter results don't return multiple results on app
        name from different locales.
        """
        app = self.apps[0]
        app.name = {'en-us': 'butter', 'fr': 'butterete', 'de': 'buttern'}
        app.save()
        ids = (_filter(Webapp.objects.all(), {'text_query': 'but'})
               .values_list('id', flat=True))

        eq_(len(ids), 1)
        assert app.id in ids

    def test_check_if_searching(self):
        """
        Test that advanced search form shown when searching fields other
        than text_query and that clear search button shown when searching.
        """
        qs = Webapp.objects.all()

        # Not searching.
        r = self.rf.get(self.url, {'text_query': '',
                                   'waiting_time_days': ''})
        qs, search_form = _get_search_form(r, qs)
        eq_(_check_if_searching(search_form), (False, False))

        # Regular searching.
        r = self.rf.get(self.url, {'text_query': 'abcd',
                                   'waiting_time_days': ''})
        qs, search_form = _get_search_form(r, qs)
        eq_(_check_if_searching(search_form), (True, False))

        # Advanced searching.
        r = self.rf.get(self.url, {'has_info_request': '1'})
        qs, search_form = _get_search_form(r, qs)
        eq_(_check_if_searching(search_form), (True, True))

    def test_do_sort(self):
        """
        Test that apps are sorted in order specified in GET params
        """
        qs = Webapp.uncached.all()

        # Test apps are sorted by created/asc by default.
        r = self.rf.get(self.url, {'sort': 'invalidsort', 'order': 'dontcare'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[1], self.apps[0]])

        # Test sorting by created, descending.
        r = self.rf.get(self.url, {'sort': 'created', 'order': 'desc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[0], self.apps[1]])

        # Test sorting by app name.
        r = self.rf.get(self.url, {'sort': 'name', 'order': 'asc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[1], self.apps[0]])

        r = self.rf.get(self.url, {'sort': 'name', 'order': 'desc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[0], self.apps[1]])

        # By abuse reports.
        AbuseReport.objects.create(addon=self.apps[1])
        r = self.rf.get(self.url, {'sort': 'num_abuse_reports',
                                   'order': 'desc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[1], self.apps[0]])
        r = self.rf.get(self.url, {'sort': 'num_abuse_reports',
                                   'order': 'asc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[0], self.apps[1]])

    def test_queue_to_app_sort(self):
        """Tests queue object's created sort order."""
        url = reverse('reviewers.apps.queue_rereview')

        earlier_rrq = RereviewQueue.objects.create(addon=self.apps[0])
        later_rrq = RereviewQueue.objects.create(addon=self.apps[1])
        later_rrq.created += datetime.timedelta(days=1)
        later_rrq.save()

        request = self.rf.get(url, {'sort': 'created'})
        apps, form = _queue_to_apps(request, RereviewQueue.objects.all())

        # Assert the order that RereviewQueue objects were created is
        # maintained.
        eq_([earlier_rrq.addon, later_rrq.addon], list(apps))

        request = self.rf.get(url, {'sort': 'created', 'order': 'desc'})
        apps, form = _queue_to_apps(request, RereviewQueue.objects.all())
        eq_([later_rrq.addon, earlier_rrq.addon], list(apps))


class TestAppsReviewing(AppReviewerTest, AccessMixin):

    def setUp(self):
        self.login_as_editor()
        super(TestAppsReviewing, self).setUp()
        self.url = reverse('reviewers.apps.apps_reviewing')
        self.apps = [app_factory(name='Antelope',
                                 status=amo.STATUS_PENDING),
                     app_factory(name='Bear',
                                 status=amo.STATUS_PENDING),
                     app_factory(name='Cougar',
                                 status=amo.STATUS_PENDING)]

    def _view_app(self, app_id):
        self.client.post(reverse('editors.review_viewing'), {
            'addon_id': app_id})

    def test_no_apps_reviewing(self):
        res = self.client.get(self.url)
        eq_(len(res.context['apps']), 0)

    def test_apps_reviewing(self):
        self._view_app(self.apps[0].id)
        res = self.client.get(self.url)
        eq_(len(res.context['apps']), 1)

    def test_multiple_reviewers_no_cross_streams(self):
        self._view_app(self.apps[0].id)
        self._view_app(self.apps[1].id)
        res = self.client.get(self.url)
        eq_(len(res.context['apps']), 2)

        # Now view an app as another user and verify app.
        self.client.login(username='admin@mozilla.com', password='password')
        self._view_app(self.apps[2].id)
        res = self.client.get(self.url)
        eq_(len(res.context['apps']), 1)

        # Check original user again to make sure app list didn't increment.
        self.login_as_editor()
        res = self.client.get(self.url)
        eq_(len(res.context['apps']), 2)
