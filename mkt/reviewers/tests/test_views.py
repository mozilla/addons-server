# -*- coding: utf-8 -*-
import datetime
import json
import os
import os.path
import time
from itertools import cycle

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.utils import translation

import mock
import requests
from nose import SkipTest
from nose.tools import eq_, ok_
from pyquery import PyQuery as pq
from requests.structures import CaseInsensitiveDict

import amo
import amo.tests
from amo.tests import req_factory_factory
import reviews
from abuse.models import AbuseReport
from access.models import Group, GroupUser
from addons.models import AddonDeviceType
from amo.helpers import absolutify
from amo.tests import (app_factory, check_links, days_ago,
                       formset, initial, version_factory)
from amo.urlresolvers import reverse
from amo.utils import isotime
from devhub.models import ActivityLog, ActivityLogAttachment, AppLog
from devhub.tests.test_models import ATTACHMENTS_DIR
from editors.models import (CannedResponse, EscalationQueue, RereviewQueue,
                            ReviewerScore)
from files.models import File
from lib.crypto import packaged
from lib.crypto.tests import mock_sign
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from versions.models import Version
from zadmin.models import get_config, set_config

import mkt
from mkt.constants.features import FeatureProfile
from mkt.reviewers.views import (_do_sort, _progress, app_review, queue_apps,
                                 route_reviewer)
from mkt.site.fixtures import fixture
from mkt.submit.tests.test_views import BasePackagedAppTest
from mkt.webapps.models import Webapp
from mkt.webapps.tests.test_models import PackagedFilesMixin


class AttachmentManagementMixin(object):
    def _attachment_management_form(self, num=1):
        """
        Generate and return data for a management form for `num` attachments
        """
        return {'attachment-TOTAL_FORMS': max(1, num),
                'attachment-INITIAL_FORMS': 0,
                'attachment-MAX_NUM_FORMS': 1000}


class AppReviewerTest(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.login_as_editor()

    def login_as_admin(self):
        self.login('admin@mozilla.com')

    def login_as_editor(self):
        self.login('editor@mozilla.com')

    def login_as_senior_reviewer(self):
        self.client.logout()
        user = UserProfile.objects.get(email='editor@mozilla.com')
        self.grant_permission(user, 'Addons:Edit,Apps:ReviewEscalated,'
                                    'Apps:ReviewPrivileged')
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
        self.packaged_app = app_factory(name='Dinosaur',
                                        status=amo.STATUS_PUBLIC,
                                        is_packaged=True)
        version_factory(addon=self.packaged_app,
                        file_kw={'status': amo.STATUS_PENDING})

        # Add a disabled app for good measure.
        app_factory(name='Elephant', disabled_by_user=True,
                    status=amo.STATUS_PENDING)

        # Escalate one app to make sure it doesn't affect stats.
        escalated = app_factory(name='Eyelash Pit Viper',
                                status=amo.STATUS_PENDING)
        EscalationQueue.objects.create(addon=escalated)

        # Add a public app under re-review.
        rereviewed = app_factory(name='Finch', status=amo.STATUS_PUBLIC)
        rq = RereviewQueue.objects.create(addon=rereviewed)
        rq.update(created=self.days_ago(1))

        # Add an app with latest update deleted. It shouldn't affect anything.
        app = app_factory(name='Great White Shark',
                          status=amo.STATUS_PUBLIC,
                          version_kw={'version': '1.0'},
                          is_packaged=True)
        v = version_factory(addon=app,
                        version='2.1',
                        file_kw={'status': amo.STATUS_PENDING})
        v.update(deleted=True)

    def test_route_reviewer(self):
        # App reviewers go to apps home.
        req = amo.tests.req_factory_factory(
            reverse('reviewers'),
            user=UserProfile.objects.get(username='editor'))
        r = route_reviewer(req)
        self.assert3xx(r, reverse('reviewers.home'))

        # App + theme reviewers go to apps home.
        group = Group.objects.get(name='App Reviewers')
        group.rules = 'Apps:Review,Personas:Review'
        group.save()

        req = amo.tests.req_factory_factory(
            reverse('reviewers'),
            user=UserProfile.objects.get(username='editor'))
        r = route_reviewer(req)
        self.assert3xx(r, reverse('reviewers.home'))

        # Theme reviewers go to themes home.
        group = Group.objects.get(name='App Reviewers')
        group.rules = 'Personas:Review'
        group.save()

        req = amo.tests.req_factory_factory(
            reverse('reviewers'),
            user=UserProfile.objects.get(username='editor'))
        r = route_reviewer(req)
        self.assert3xx(r, reverse('reviewers.themes.home'))

    def test_progress_pending(self):
        self.apps[0].latest_version.update(nomination=self.days_ago(1))
        self.apps[1].latest_version.update(nomination=self.days_ago(8))
        self.apps[2].latest_version.update(nomination=self.days_ago(15))
        counts, percentages = _progress()
        eq_(counts['pending']['week'], 1)
        eq_(counts['pending']['new'], 1)
        eq_(counts['pending']['old'], 1)
        eq_(counts['pending']['med'], 1)
        self.assertAlmostEqual(percentages['pending']['new'], 33.333333333333)
        self.assertAlmostEqual(percentages['pending']['old'], 33.333333333333)
        self.assertAlmostEqual(percentages['pending']['med'], 33.333333333333)

    def test_progress_rereview(self):
        rq = RereviewQueue.objects.create(addon=self.apps[0])
        rq.update(created=self.days_ago(8))
        rq = RereviewQueue.objects.create(addon=self.apps[1])
        rq.update(created=self.days_ago(15))
        counts, percentages = _progress()
        eq_(counts['rereview']['week'], 1)
        eq_(counts['rereview']['new'], 1)
        eq_(counts['rereview']['old'], 1)
        eq_(counts['rereview']['med'], 1)
        self.assertAlmostEqual(percentages['rereview']['new'], 33.333333333333)
        self.assertAlmostEqual(percentages['rereview']['old'], 33.333333333333)
        self.assertAlmostEqual(percentages['rereview']['med'], 33.333333333333)

    def test_progress_updated(self):
        extra_app = app_factory(name='Jackalope',
                                status=amo.STATUS_PUBLIC,
                                is_packaged=True,
                                created=self.days_ago(35))
        version_factory(addon=extra_app,
                        file_kw={'status': amo.STATUS_PENDING},
                        created=self.days_ago(25),
                        nomination=self.days_ago(8))
        extra_app = app_factory(name='Jackrabbit',
                                status=amo.STATUS_PUBLIC,
                                is_packaged=True,
                                created=self.days_ago(35))
        version_factory(addon=extra_app,
                        file_kw={'status': amo.STATUS_PENDING},
                        created=self.days_ago(25),
                        nomination=self.days_ago(25))
        counts, percentages = _progress()
        eq_(counts['updates']['week'], 1)
        eq_(counts['updates']['new'], 1)
        eq_(counts['updates']['old'], 1)
        eq_(counts['updates']['med'], 1)
        self.assertAlmostEqual(percentages['updates']['new'], 33.333333333333)
        self.assertAlmostEqual(percentages['updates']['old'], 33.333333333333)
        self.assertAlmostEqual(percentages['updates']['med'], 33.333333333333)

    def test_stats_waiting(self):
        self.apps[0].latest_version.update(nomination=self.days_ago(1))
        self.apps[1].latest_version.update(nomination=self.days_ago(5))
        self.apps[2].latest_version.update(nomination=self.days_ago(15))
        self.packaged_app.update(created=self.days_ago(1))

        doc = pq(self.client.get(self.url).content)

        anchors = doc('.editor-stats-title a')
        eq_(anchors.eq(0).text(), '3 Pending App Reviews')
        eq_(anchors.eq(1).text(), '1 Re-review')
        eq_(anchors.eq(2).text(), '1 Update Review')

        divs = doc('.editor-stats-table > div')

        # Pending review.
        eq_(divs.eq(0).text(), '2 unreviewed app submissions this week.')

        # Re-reviews.
        eq_(divs.eq(2).text(), '1 unreviewed app submission this week.')

        # Update review.
        eq_(divs.eq(4).text(), '1 unreviewed app submission this week.')

        # Maths.
        # Pending review.
        eq_(doc('.waiting_new').eq(0).attr('title')[-3:], '33%')
        eq_(doc('.waiting_med').eq(0).attr('title')[-3:], '33%')
        eq_(doc('.waiting_old').eq(0).attr('title')[-3:], '33%')

        # Re-reviews.
        eq_(doc('.waiting_new').eq(1).attr('title')[-4:], '100%')
        eq_(doc('.waiting_med').eq(1).attr('title')[-3:], ' 0%')
        eq_(doc('.waiting_old').eq(1).attr('title')[-3:], ' 0%')

        # Update review.
        eq_(doc('.waiting_new').eq(2).attr('title')[-4:], '100%')
        eq_(doc('.waiting_med').eq(2).attr('title')[-3:], ' 0%')
        eq_(doc('.waiting_old').eq(2).attr('title')[-3:], ' 0%')

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
        td = pq(res.content)('#addon-queue tbody tr td.flags').eq(0)
        flag = td('div.sprite-reviewer-packaged-app')
        eq_(flag.length, 1)

    def test_flag_premium_app(self):
        self.apps[0].update(premium_type=amo.ADDON_PREMIUM)
        eq_(self.apps[0].is_premium(), True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td.flags')
        flags = tds('div.sprite-reviewer-premium')
        eq_(flags.length, 1)

    def test_flag_free_inapp_app(self):
        self.apps[0].update(premium_type=amo.ADDON_FREE_INAPP)
        res = self.client.get(self.url)
        tds = pq(res.content)('#addon-queue tbody tr td.flags')
        eq_(tds('div.sprite-reviewer-premium.inapp.free').length, 1)

    def test_flag_premium_inapp_app(self):
        self.apps[0].update(premium_type=amo.ADDON_PREMIUM_INAPP)
        res = self.client.get(self.url)
        tds = pq(res.content)('#addon-queue tbody tr td.flags')
        eq_(tds('div.sprite-reviewer-premium.inapp').length, 1)

    def test_flag_info(self):
        self.apps[0].current_version.update(has_info_request=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td.flags')
        flags = tds('div.sprite-reviewer-info')
        eq_(flags.length, 1)

    def test_flag_comment(self):
        self.apps[0].current_version.update(has_editor_comment=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        tds = pq(res.content)('#addon-queue tbody tr td.flags')
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
                                 status=amo.STATUS_PENDING,
                                 version_kw={'nomination': self.days_ago(2)},
                                 file_kw={'status': amo.STATUS_PENDING}),
                     app_factory(name='YYY',
                                 status=amo.STATUS_PENDING,
                                 version_kw={'nomination': self.days_ago(1)},
                                 file_kw={'status': amo.STATUS_PENDING}),
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

    @mock.patch('versions.models.Version.is_privileged', True)
    def test_action_buttons_privileged_cantreview(self):
        self.apps[0].update(is_packaged=True)
        self.apps[0].latest_version.files.update(status=amo.STATUS_PENDING)
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Escalate', 'escalate'),
            (u'Request more information', 'info'),
            (u'Comment', 'comment'),
        ]
        self.check_actions(expected, actions)

    @mock.patch('versions.models.Version.is_privileged', True)
    def test_action_buttons_privileged_canreview(self):
        self.login_as_senior_reviewer()
        self.apps[0].update(is_packaged=True)
        self.apps[0].latest_version.files.update(status=amo.STATUS_PENDING)
        r = self.client.get(self.review_url(self.apps[0]))
        eq_(r.status_code, 200)
        actions = pq(r.content)('#review-actions input')
        expected = [
            (u'Push to public', 'public'),
            (u'Reject', 'reject'),
            (u'Disable app', 'disable'),
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
        eq_(tds.eq(0).text(),
            unicode(amo.ADDON_PREMIUM_TYPES[amo.ADDON_PREMIUM]))
        eq_(tds.eq(1).text(),
            unicode(amo.ADDON_PREMIUM_TYPES[amo.ADDON_FREE_INAPP]))

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

    def test_incomplete_no_in_queue(self):
        # Test waffle-less.
        [app.update(status=amo.STATUS_NULL) for app in self.apps]
        req = req_factory_factory(self.url,
            user=UserProfile.objects.get(username='editor'))
        doc = pq(queue_apps(req).content)
        assert not doc('#addon-queue tbody tr').length


class TestRegionQueue(AppReviewerTest, AccessMixin, FlagsMixin, SearchMixin,
                      XSSMixin):
    fixtures = ['base/users']

    def setUp(self):
        self.apps = [app_factory(name='WWW',
                                 status=amo.STATUS_PUBLIC),
                     app_factory(name='XXX',
                                 status=amo.STATUS_PUBLIC),
                     app_factory(name='YYY',
                                 status=amo.STATUS_PUBLIC),
                     app_factory(name='ZZZ',
                                 status=amo.STATUS_PENDING)]
        # WWW and XXX are the only ones actually requested to be public.
        self.apps[0].geodata.update(region_cn_status=amo.STATUS_PENDING,
            region_cn_nominated=self.days_ago(2))
        self.apps[1].geodata.update(region_cn_status=amo.STATUS_PENDING,
            region_cn_nominated=self.days_ago(1))
        self.apps[2].geodata.update(region_cn_status=amo.STATUS_PUBLIC)

        self.user = UserProfile.objects.get(username='editor')
        self.grant_permission(self.user, 'Apps:ReviewRegionCN')
        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_region',
                           args=[mkt.regions.CN.slug])

    def test_template_links(self):
        raise SkipTest, 'TODO(cvan): Figure out sorting issue'

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        links = pq(r.content)('.regional-queue tbody tr td:first-child a')
        apps = Webapp.objects.order_by('-_geodata__region_cn_nominated')
        src = '?src=queue-region-cn'
        expected = [
            (unicode(apps[0].name), apps[0].get_url_path() + src),
            (unicode(apps[1].name), apps[1].get_url_path() + src),
        ]
        check_links(expected, links, verify=False)

    def test_escalated_not_in_queue(self):
        self.login_as_senior_reviewer()
        self.apps[0].escalationqueue_set.create()
        res = self.client.get(self.url)
        eq_([a.app for a in res.context['addons']], [self.apps[1]])


@mock.patch('versions.models.Version.is_privileged', False)
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
        app = self.apps[0]
        app.delete()
        eq_(RereviewQueue.objects.filter(addon=app).exists(), False)


@mock.patch('versions.models.Version.is_privileged', False)
class TestUpdateQueue(AppReviewerTest, AccessMixin, FlagsMixin, SearchMixin,
                      XSSMixin):
    fixtures = ['base/users']

    def setUp(self):
        app1 = app_factory(is_packaged=True, name='XXX',
                           version_kw={'version': '1.0',
                                       'created': self.days_ago(2),
                                       'nomination': self.days_ago(2)})
        app2 = app_factory(is_packaged=True, name='YYY',
                           version_kw={'version': '1.0',
                                       'created': self.days_ago(2),
                                       'nomination': self.days_ago(2)})

        version_factory(addon=app1, version='1.1', created=self.days_ago(1),
                        nomination=self.days_ago(1),
                        file_kw={'status': amo.STATUS_PENDING})
        version_factory(addon=app2, version='1.1', created=self.days_ago(1),
                        nomination=self.days_ago(1),
                        file_kw={'status': amo.STATUS_PENDING})

        self.apps = list(Webapp.objects.order_by('id'))
        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_updates')

    def review_url(self, app):
        return reverse('reviewers.apps.review', args=[app.app_slug])

    def test_template_links(self):
        self.apps[0].versions.latest().update(nomination=self.days_ago(2))
        self.apps[1].versions.latest().update(nomination=self.days_ago(1))
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
        self.apps[0].versions.latest().update(nomination=self.days_ago(1))
        self.apps[1].versions.latest().update(nomination=self.days_ago(4))
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

    def test_public_waiting_update_in_queue(self):
        app = app_factory(is_packaged=True, name='YYY',
                          status=amo.STATUS_PUBLIC_WAITING,
                          version_kw={'version': '1.0',
                                      'created': self.days_ago(2),
                                      'nomination': self.days_ago(2)})
        File.objects.filter(version__addon=app).update(status=app.status)

        version_factory(addon=app, version='1.1', created=self.days_ago(1),
                        nomination=self.days_ago(1),
                        file_kw={'status': amo.STATUS_PENDING})

        res = self.client.get(self.url)
        apps = [a.app for a in res.context['addons']]
        assert app in apps
        eq_(pq(res.content)('.tabnav li a:eq(2)').text(), u'Updates (3)')

    def test_update_queue_with_empty_nomination(self):
        app = app_factory(is_packaged=True, name='YYY',
                          status=amo.STATUS_NULL,
                          version_kw={'version': '1.0',
                                      'created': self.days_ago(2),
                                      'nomination': None})
        first_version = app.latest_version
        version_factory(addon=app, version='1.1', created=self.days_ago(1),
                        nomination=None,
                        file_kw={'status': amo.STATUS_PENDING})

        # Now that we have a version with nomination=None, reset app status.
        app.update(status=amo.STATUS_PUBLIC_WAITING)
        File.objects.filter(version=first_version).update(status=app.status)

        # Safeguard: we /really/ want to test with nomination=None.
        eq_(app.latest_version.reload().nomination, None)

        res = self.client.get(self.url)
        apps = [a.app for a in res.context['addons']]
        assert app in apps
        eq_(pq(res.content)('.tabnav li a:eq(2)').text(), u'Updates (3)')

    @mock.patch('mkt.webapps.tasks.update_cached_manifests')
    def test_deleted_version_not_in_queue(self, _mock):
        """
        This tests that an app with a prior pending version that got
        deleted doesn't trigger the app to remain in the review queue.
        """
        app = self.apps[0]
        # File is PENDING and delete current version.
        old_ver = app.versions.order_by('id')[0]
        old_ver.files.latest().update(status=amo.STATUS_PENDING)
        old_ver.delete()
        # "Approve" the app.
        app.update(status=amo.STATUS_PUBLIC)
        app.versions.latest().files.latest().update(status=amo.STATUS_PUBLIC)

        res = self.client.get(self.url)
        eq_(res.status_code, 200)

        # Verify that our app has 2 versions.
        eq_(Version.with_deleted.filter(addon=app).count(), 2)

        # Verify the apps in the context are what we expect.
        doc = pq(res.content)
        eq_(doc('.tabnav li a:eq(2)').text(), u'Updates (1)')
        apps = [a.app for a in res.context['addons']]
        ok_(app not in apps)
        ok_(self.apps[1] in apps)


class TestDeviceQueue(AppReviewerTest, AccessMixin):
    fixtures = fixture('group_editor', 'user_editor', 'user_editor_group',
                       'user_999')

    def setUp(self):
        self.create_switch('buchets')

        self.app1 = app_factory(name='XXX',
                                version_kw={'version': '1.0',
                                            'created': self.days_ago(2),
                                            'nomination': self.days_ago(2)})
        self.app1.versions.latest().features.update(has_sms=True)

        self.app2 = app_factory(name='YYY',
                                version_kw={'version': '1.0',
                                            'created': self.days_ago(2),
                                            'nomination': self.days_ago(2)})
        self.app2.versions.latest().features.update(has_mp3=True)

        self.app1.update(status=amo.STATUS_PENDING)
        self.app2.update(status=amo.STATUS_PENDING)

        self.apps = list(Webapp.objects.order_by('id'))
        self.login_as_editor()
        self.url = reverse('reviewers.apps.queue_device')

    def test_no_queue_if_no_pro(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        ok_('queue_device' not in res.context['queue_counts'])
        eq_(res.context['addons'], [])

    def test_queue_filters(self):
        "Test queue filters out apps we don't support."
        pro = FeatureProfile(sms=True).to_signature()
        res = self.client.get(self.url, {'pro': pro})
        eq_(res.status_code, 200)
        eq_(res.context['queue_counts']['device'], 1)
        apps = [a.app for a in res.context['addons']]
        ok_(self.app1 in apps)
        ok_(self.app2 not in apps)


@mock.patch('versions.models.Version.is_privileged', False)
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
        tds = pq(res.content)('#addon-queue tbody tr td.flags')
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
        app = self.apps[0]
        app.delete()
        eq_(EscalationQueue.objects.filter(addon=app).exists(), False)


class TestReviewTransaction(AttachmentManagementMixin, amo.tests.MockEsMixin,
                            amo.tests.test_utils.TransactionTestCase):
    fixtures = fixture('group_editor', 'user_editor', 'user_editor_group',
                       'webapp_337141')

    def get_app(self):
        return Webapp.objects.no_cache().get(id=337141)

    @mock.patch('mkt.webapps.models.Webapp.get_manifest_json')
    @mock.patch('lib.crypto.packaged.sign_app')
    def test_public_sign(self, sign_mock, json_mock):
        self.app = self.get_app()
        self.app.update(status=amo.STATUS_PENDING, is_packaged=True)
        self.version = self.app.current_version
        self.version.files.all().update(status=amo.STATUS_PENDING)
        eq_(self.get_app().status, amo.STATUS_PENDING)

        sign_mock.return_value = None  # Didn't fail.
        json_mock.return_value = {'name': 'Something'}

        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        resp = self.client.post(
            reverse('reviewers.apps.review', args=[self.app.app_slug]),
            data)
        eq_(resp.status_code, 302)

        eq_(self.get_app().status, amo.STATUS_PUBLIC)

    @mock.patch('lib.crypto.packaged.sign_app')
    def test_public_sign_failure(self, sign_mock):
        # Test fails only on Jenkins, so skipping when run there for now.
        if os.environ.get('JENKINS_HOME'):
            raise SkipTest()

        self.app = self.get_app()
        self.app.update(status=amo.STATUS_PENDING, is_packaged=True)
        self.version = self.app.current_version
        self.version.files.all().update(status=amo.STATUS_PENDING)
        # Test fails on Jenkins on the line below; status is STATUS_PUBLIC.
        eq_(self.get_app().status, amo.STATUS_PENDING)

        sign_mock.side_effect = packaged.SigningError('Bad things happened.')

        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        resp = self.client.post(
            reverse('reviewers.apps.review', args=[self.app.app_slug]), data)
        eq_(resp.status_code, 302)

        eq_(self.get_app().status, amo.STATUS_PENDING)


class TestReviewApp(AppReviewerTest, AccessMixin, AttachmentManagementMixin,
                    PackagedFilesMixin):
    fixtures = ['base/platforms', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestReviewApp, self).setUp()
        self.create_switch('iarc', db=True)
        self.mozilla_contact = 'contact@mozilla.com'
        self.app = self.get_app()
        self.app = amo.tests.make_game(self.app, True)
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

    def test_cannot_review_my_app(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            self.app.addonuser_set.create(
                user=UserProfile.objects.get(username='editor'))
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

    def test_review_no_latest_version(self):
        self.app.versions.all().delete()
        self.app.reload()
        eq_(self.app.latest_version, None)
        eq_(self.app.current_version, None)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        doc = pq(response.content)
        assert doc('input[name=action][value=info]').length
        assert doc('input[name=action][value=comment]').length
        assert not doc('input[name=action][value=public]').length
        assert not doc('input[name=action][value=reject]').length

        # Also try with a packaged app.
        self.app.update(is_packaged=True)
        response = self.client.get(self.url)
        eq_(response.status_code, 200)

    def test_sr_can_review_blocklisted_app(self):
        self.app.update(status=amo.STATUS_BLOCKED)
        self.login_as_senior_reviewer()
        eq_(self.client.get(self.url).status_code, 200)
        data = {'action': 'public', 'comments': 'yo'}
        data.update(self._attachment_management_form(num=0))
        res = self.client.post(self.url, data)
        self.assert3xx(res, reverse('reviewers.apps.queue_pending'))

    def _check_email(self, msg, subject, with_mozilla_contact=True):
        eq_(msg.to, list(self.app.authors.values_list('email', flat=True)))
        if with_mozilla_contact:
            eq_(msg.cc, [self.mozilla_contact])
        else:
            eq_(msg.cc, [])
        eq_(msg.subject, '%s: %s' % (subject, self.app.name))
        eq_(msg.from_email, settings.MKT_REVIEWERS_EMAIL)
        eq_(msg.extra_headers['Reply-To'], settings.MKT_REVIEWERS_EMAIL)

    def _check_thread(self):
        thread = self.app.threads
        eq_(thread.count(), 1)

        thread = thread.get()
        perms = ('developer', 'reviewer', 'staff')

        for key in perms:
            assert getattr(thread, 'read_permission_%s' % key)

    def _check_admin_email(self, msg, subject):
        eq_(msg.to, [settings.MKT_SENIOR_EDITORS_EMAIL])
        eq_(msg.subject, '%s: %s' % (subject, self.app.name))
        eq_(msg.from_email, settings.MKT_REVIEWERS_EMAIL)
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

    def test_comm_emails(self):
        data = {'action': 'reject', 'comments': 'suxor',
                'action_visibility': ('developer', 'reviewer', 'staff')}
        data.update(self._attachment_management_form(num=0))
        self.create_switch(name='comm-dashboard')
        self.post(data)
        self._check_thread()

        recipients = set(self.app.authors.values_list('email', flat=True))
        recipients.update(Group.objects.get(
            name='App Reviewers').users.values_list('email', flat=True))
        recipients.update(Group.objects.get(
            name='Admins').users.values_list('email', flat=True))

        recipients.remove('editor@mozilla.com')

        eq_(len(mail.outbox), len(recipients))
        eq_(mail.outbox[0].subject, '%s has been reviewed.' %
            self.get_app().name)

    def test_xss(self):
        data = {'action': 'comment',
                'comments': '<script>alert("xss")</script>'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        res = self.client.get(self.url)
        assert '<script>alert' not in res.content
        assert '&lt;script&gt;alert' in res.content

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    def test_pending_to_public_w_device_overrides(self, storefront_mock):
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_DESKTOP.id)
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_TABLET.id)
        eq_(self.app.make_public, amo.PUBLIC_IMMEDIATELY)
        data = {'action': 'public', 'device_types': '', 'browsers': '',
                'comments': 'something',
                'device_override': [amo.DEVICE_DESKTOP.id]}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.make_public, amo.PUBLIC_WAIT)
        eq_(app.status, amo.STATUS_PUBLIC_WAITING)
        eq_([o.id for o in app.device_types], [amo.DEVICE_DESKTOP.id])
        self._check_log(amo.LOG.REVIEW_DEVICE_OVERRIDE)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved but waiting')
        self._check_email_body(msg)

        assert not storefront_mock.called

    def test_pending_to_reject_w_device_overrides(self):
        # This shouldn't be possible unless there's form hacking.
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_DESKTOP.id)
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_TABLET.id)
        eq_(self.app.make_public, amo.PUBLIC_IMMEDIATELY)
        data = {'action': 'reject', 'device_types': '', 'browsers': '',
                'comments': 'something',
                'device_override': [amo.DEVICE_DESKTOP.id]}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.make_public, amo.PUBLIC_IMMEDIATELY)
        eq_(app.status, amo.STATUS_REJECTED)
        eq_(set([o.id for o in app.device_types]),
            set([amo.DEVICE_DESKTOP.id, amo.DEVICE_TABLET.id]))

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    def test_pending_to_public_w_requirements_overrides(self, storefront_mock):
        self.create_switch(name='buchets')
        data = {'action': 'public', 'comments': 'something',
                'has_sms': True}
        data.update(self._attachment_management_form(num=0))
        assert not self.app.current_version.features.has_sms
        self.post(data)
        app = self.get_app()
        assert app.current_version.features.has_sms
        eq_(app.make_public, amo.PUBLIC_WAIT)
        eq_(app.status, amo.STATUS_PUBLIC_WAITING)
        self._check_log(amo.LOG.REVIEW_FEATURES_OVERRIDE)

        # A reviewer changing features shouldn't generate a re-review.
        eq_(RereviewQueue.objects.count(), 0)

        assert not storefront_mock.called

    def test_pending_to_reject_w_requirements_overrides(self):
        # Rejecting an app doesn't let you override features requirements.
        self.create_switch(name='buchets')
        data = {'action': 'reject', 'comments': 'something',
                'has_sms': True}
        data.update(self._attachment_management_form(num=0))
        assert not self.app.current_version.features.has_sms
        self.post(data)
        app = self.get_app()
        eq_(app.make_public, amo.PUBLIC_IMMEDIATELY)
        eq_(app.status, amo.STATUS_REJECTED)
        assert not app.current_version.features.has_sms

    def test_pending_to_reject_w_requirements_overrides_nothing_changed(self):
        self.version.features.update(has_sms=True)
        self.create_switch(name='buchets')
        data = {'action': 'public', 'comments': 'something',
                'has_sms': True}
        data.update(self._attachment_management_form(num=0))
        assert self.app.current_version.features.has_sms
        self.post(data)
        app = self.get_app()
        assert app.current_version.features.has_sms
        eq_(app.make_public, None)
        eq_(app.status, amo.STATUS_PUBLIC)
        action_id = amo.LOG.REVIEW_FEATURES_OVERRIDE.id
        assert not AppLog.objects.filter(
            addon=self.app, activity_log__action=action_id).exists()

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    @mock.patch('mkt.reviewers.views.messages.success')
    @mock.patch('addons.tasks.index_addons')
    @mock.patch('mkt.webapps.models.Webapp.update_supported_locales')
    @mock.patch('mkt.webapps.models.Webapp.update_name_from_package_manifest')
    def test_pending_to_public(self, update_name, update_locales,
                               index_addons, messages, storefront_mock):
        data = {'action': 'public', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_PUBLIC)
        self._check_log(amo.LOG.APPROVE_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

        assert update_name.called
        assert update_locales.called

        # It's zero for the view but happens after the transaction commits. If
        # this increases we could get tasks being called with stale data.
        eq_(index_addons.delay.call_count, 0)

        eq_(messages.call_args_list[0][0][1],
            '"Web App Review" successfully processed (+60 points, 60 total).')

        assert storefront_mock.called

    @mock.patch('mkt.reviewers.views.messages.success', new=mock.Mock)
    def test_incomplete_cant_approve(self):
        self.app.update(status=amo.STATUS_NULL)
        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)

        # Still incomplete.
        eq_(self.get_app().status, amo.STATUS_NULL)

    def test_notification_email_translation(self):
        """Test that the app name is translated with the app's default_locale
        and not the reviewer's when we are sending notification emails."""
        original_name = unicode(self.app.name)
        fr_translation = u'Mais allô quoi!'
        es_translation = u'¿Dónde está la biblioteca?'
        self.app.name = {
            'fr': fr_translation,
            'es': es_translation,
        }
        self.app.default_locale = 'fr'
        self.app.save()

        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.client.post(self.url, data, HTTP_ACCEPT_LANGUAGE='es')
        eq_(translation.get_language(), 'es')

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]

        assert not original_name in msg.subject
        assert not es_translation in msg.subject
        assert fr_translation in msg.subject
        assert not original_name in msg.body
        assert not es_translation in msg.body
        assert fr_translation in msg.body

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    @mock.patch('lib.crypto.packaged.sign')
    def test_public_signs(self, sign, storefront_mock):
        self.get_app().update(is_packaged=True)
        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)

        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(sign.call_args[0][0], self.get_app().current_version.pk)

        assert storefront_mock.called

    @mock.patch('lib.crypto.packaged.sign')
    def test_require_sig_for_public(self, sign):
        sign.side_effect = packaged.SigningError
        self.get_app().update(is_packaged=True)
        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.client.post(self.url, data)
        eq_(self.get_app().status, amo.STATUS_PENDING)

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    def test_pending_to_public_no_mozilla_contact(self, storefront_mock):
        self.app.update(mozilla_contact='')
        data = {'action': 'public', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_PUBLIC)
        self._check_log(amo.LOG.APPROVE_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved', with_mozilla_contact=False)
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

        assert storefront_mock.called

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    @mock.patch('addons.tasks.index_addons')
    @mock.patch('mkt.webapps.models.Webapp.update_supported_locales')
    @mock.patch('mkt.webapps.models.Webapp.update_name_from_package_manifest')
    def test_pending_to_public_waiting(self, update_name, update_locales,
                                       index_addons, storefront_mock):
        self.get_app().update(_signal=False, make_public=amo.PUBLIC_WAIT)
        index_addons.delay.reset_mock()

        data = {'action': 'public', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC_WAITING)
        eq_(app._current_version.files.all()[0].status,
            amo.STATUS_PUBLIC_WAITING)
        self._check_log(amo.LOG.APPROVE_VERSION_WAITING)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved but waiting')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_HOSTED)

        assert not update_name.called
        assert not update_locales.called

        # It's zero for the view but happens after the transaction commits. If
        # this increases we could get tasks being called with stale data.
        eq_(index_addons.delay.call_count, 0)

        assert not storefront_mock.called

    @mock.patch('lib.crypto.packaged.sign')
    def test_public_waiting_signs(self, sign):
        self.get_app().update(is_packaged=True, make_public=amo.PUBLIC_WAIT)
        data = {'action': 'public', 'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)

        eq_(self.get_app().status, amo.STATUS_PUBLIC_WAITING)
        eq_(sign.call_args[0][0], self.get_app().current_version.pk)

    def test_pending_to_reject(self):
        files = list(self.version.files.values_list('id', flat=True))
        data = {'action': 'reject', 'comments': 'suxor'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
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
        data = {'action': 'reject', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.status, amo.STATUS_REJECTED)
        eq_(new_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.REJECT_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)

    def test_multiple_versions_reject_packaged(self):
        self.app.update(status=amo.STATUS_PUBLIC, is_packaged=True)
        self.app.current_version.files.update(status=amo.STATUS_PUBLIC)
        new_version = version_factory(addon=self.app)
        new_version.files.all().update(status=amo.STATUS_PENDING)
        data = {'action': 'reject', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(new_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.REJECT_VERSION)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')
        self._check_email_body(msg)
        self._check_score(amo.REVIEWED_WEBAPP_UPDATE)

    @mock.patch('mkt.reviewers.views.messages.success')
    def test_pending_to_escalation(self, messages):
        data = {'action': 'escalate', 'comments': 'soup her man'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        eq_(EscalationQueue.objects.count(), 1)
        self._check_log(amo.LOG.ESCALATE_MANUAL)
        # Test 2 emails: 1 to dev, 1 to admin.
        eq_(len(mail.outbox), 2)
        dev_msg = mail.outbox[0]
        self._check_email(dev_msg, 'Submission Update')
        adm_msg = mail.outbox[1]
        self._check_admin_email(adm_msg, 'Escalated Review Requested')

        eq_(messages.call_args_list[0][0][1], 'Review successfully processed.')

    def test_pending_to_disable_senior_reviewer(self):
        self.login_as_senior_reviewer()

        self.app.update(status=amo.STATUS_PUBLIC)
        data = {'action': 'disable', 'comments': 'disabled ur app'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        app = self.get_app()
        eq_(app.status, amo.STATUS_DISABLED)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.APP_DISABLED)
        eq_(len(mail.outbox), 1)
        self._check_email(mail.outbox[0], 'App disabled by reviewer')

    def test_pending_to_disable(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        data = {'action': 'disable', 'comments': 'disabled ur app'}
        data.update(self._attachment_management_form(num=0))
        res = self.client.post(self.url, data)
        eq_(res.status_code, 200)
        ok_('action' in res.context['form'].errors)
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(len(mail.outbox), 0)

    @mock.patch('mkt.webapps.models.Webapp.set_iarc_storefront_data')
    def test_escalation_to_public(self, storefront_mock):
        EscalationQueue.objects.create(addon=self.app)
        eq_(self.app.status, amo.STATUS_PENDING)
        data = {'action': 'public', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='escalated')
        app = self.get_app()
        eq_(app.status, amo.STATUS_PUBLIC)
        eq_(app.current_version.files.all()[0].status, amo.STATUS_PUBLIC)
        self._check_log(amo.LOG.APPROVE_VERSION)
        eq_(EscalationQueue.objects.count(), 0)

        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'App Approved')
        self._check_email_body(msg)

        assert storefront_mock.called

    def test_escalation_to_reject(self):
        EscalationQueue.objects.create(addon=self.app)
        eq_(self.app.status, amo.STATUS_PENDING)
        files = list(self.version.files.values_list('id', flat=True))
        data = {'action': 'reject', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='escalated')
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
        data = {'action': 'disable', 'comments': 'disabled ur app'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='escalated')
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
        data = {'action': 'disable', 'comments': 'disabled ur app'}
        data.update(self._attachment_management_form(num=0))
        res = self.client.post(self.url, data, queue='escalated')
        eq_(res.status_code, 200)
        ok_('action' in res.context['form'].errors)
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(EscalationQueue.objects.count(), 1)
        eq_(len(mail.outbox), 0)

    def test_clear_escalation(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        EscalationQueue.objects.create(addon=self.app)
        data = {'action': 'clear_escalation', 'comments': 'all clear'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='escalated')
        eq_(EscalationQueue.objects.count(), 0)
        self._check_log(amo.LOG.ESCALATION_CLEARED)
        # Ensure we don't send email on clearing escalations.
        eq_(len(mail.outbox), 0)

    def test_rereview_to_reject(self):
        RereviewQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        data = {'action': 'reject', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='rereview')
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
        data = {'action': 'disable', 'device_types': '', 'browsers': '',
                'comments': 'something'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='rereview')
        eq_(self.get_app().status, amo.STATUS_DISABLED)
        self._check_log(amo.LOG.APP_DISABLED)
        eq_(RereviewQueue.objects.filter(addon=self.app).count(), 0)
        eq_(len(mail.outbox), 1)
        self._check_email(mail.outbox[0], 'App disabled by reviewer')

    def test_rereview_to_disable(self):
        RereviewQueue.objects.create(addon=self.app)
        self.app.update(status=amo.STATUS_PUBLIC)
        data = {'action': 'disable', 'comments': 'disabled ur app'}
        data.update(self._attachment_management_form(num=0))
        res = self.client.post(self.url, data, queue='rereview')
        eq_(res.status_code, 200)
        ok_('action' in res.context['form'].errors)
        eq_(self.get_app().status, amo.STATUS_PUBLIC)
        eq_(RereviewQueue.objects.filter(addon=self.app).count(), 1)
        eq_(len(mail.outbox), 0)

    def test_clear_rereview(self):
        self.app.update(status=amo.STATUS_PUBLIC)
        RereviewQueue.objects.create(addon=self.app)
        data = {'action': 'clear_rereview', 'comments': 'all clear'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='rereview')
        eq_(RereviewQueue.objects.count(), 0)
        self._check_log(amo.LOG.REREVIEW_CLEARED)
        # Ensure we don't send email on clearing re-reviews..
        eq_(len(mail.outbox), 0)
        self._check_score(amo.REVIEWED_WEBAPP_REREVIEW)

    def test_rereview_to_escalation(self):
        RereviewQueue.objects.create(addon=self.app)
        data = {'action': 'escalate', 'comments': 'soup her man'}
        data.update(self._attachment_management_form(num=0))
        self.post(data, queue='rereview')
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
        data = {'action': 'info', 'comments': 'Knead moor in faux'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        eq_(self.get_app().status, amo.STATUS_PENDING)
        self._check_log(amo.LOG.REQUEST_INFORMATION)
        vqs = self.get_app().versions.all()
        eq_(vqs.count(), 1)
        eq_(vqs.filter(has_info_request=True).count(), 1)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')

    def test_multi_cc_email(self):
        # Test multiple mozilla_contact emails via more information.
        contacts = [u'á@b.com', u'ç@d.com']
        self.mozilla_contact = ', '.join(contacts)
        self.app.update(mozilla_contact=self.mozilla_contact)
        data = {'action': 'info', 'comments': 'Knead moor in faux'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self._check_email(msg, 'Submission Update')

    def test_comment(self):
        # Test the same for all queues.
        data = {'action': 'comment', 'comments': 'mmm, nice app'}
        data.update(self._attachment_management_form(num=0))
        self.post(data)
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
        m.headers = CaseInsensitiveDict({'content-type':
                     'application/x-web-app-manifest+json <script>'})
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
        m.headers = CaseInsensitiveDict({})
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
        m.headers = CaseInsensitiveDict({})
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
        m.headers = CaseInsensitiveDict({})
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
        m.headers = CaseInsensitiveDict({})
        mock_get.side_effect = requests.exceptions.SSLError
        mock_get.return_value = m

        # We should not 500 on a traceback.

        r = self.client.get(reverse('reviewers.apps.review.manifest',
                                    args=[self.app.app_slug]))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert data['content'], 'There should be a content with the traceback'
        eq_(data['headers'], {})

    @mock.patch('mkt.reviewers.views.json.dumps')
    def test_manifest_json_packaged(self, mock_):
        # Test that when the app is packaged, _mini_manifest is called.
        mock_.return_value = '{}'

        self.get_app().update(is_packaged=True)
        res = self.client.get(reverse('reviewers.apps.review.manifest',
                                      args=[self.app.app_slug]))
        eq_(res.status_code, 200)
        assert mock_.called

    @mock.patch('mkt.reviewers.views._get_manifest_json')
    def test_manifest_json_perms(self, mock_):
        mock_.return_value = {
            'permissions': {
                "foo": {"description": "foo"},
                "camera": {"description": "<script>"}
            }
        }

        self.get_app().update(is_packaged=True)
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

    def _attachments(self, num):
        """ Generate and return data for `num` attachments """
        data = {}
        files = ['bacon.jpg', 'bacon.txt']
        descriptions = ['mmm, bacon', '']
        if num > 0:
            for n in xrange(num):
                i = 0 if n % 2 else 1
                path = os.path.join(settings.REVIEWER_ATTACHMENTS_PATH,
                                    files[i])
                attachment = open(path)
                data.update({
                    'attachment-%d-attachment' % n: attachment,
                    'attachment-%d-description' % n: descriptions[i]
                })
        return data

    def _attachment_form_data(self, num=1, action='comment'):
        data = {'action': action,
                'comments': 'mmm, nice app'}
        data.update(self._attachment_management_form(num=num))
        data.update(self._attachments(num))
        return data

    def _attachment_post(self, num):
        """
        Test that `num` attachment objects are successfully created by the
        appropriate form submission. Tests this in two ways:

        1) Ensuring that the form is submitted correctly.
        2) Checking that the appropriate number of objects are created.
        """
        old_attachment_count = ActivityLogAttachment.objects.all().count()
        self.post(self._attachment_form_data(num=num))
        new_attachment_count = ActivityLogAttachment.objects.all().count()
        eq_(new_attachment_count - old_attachment_count, num,
            'AcitvityLog objects not being created')

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_no_attachments(self, save_mock):
        """ Test addition of no attachment """
        self.post(self._attachment_form_data(num=0, action='public'))
        eq_(save_mock.called, False, save_mock.call_args_list)

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_attachment(self, save_mock):
        """ Test addition of 1 attachment """
        self._attachment_post(1)
        eq_(save_mock.call_args_list,
            [mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.txt'), mock.ANY)])

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_multiple_attachments(self, save_mock):
        """ Test addition of multiple attachments """
        self._attachment_post(2)
        eq_(save_mock.call_args_list,
            [mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.txt'), mock.ANY),
             mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.jpg'), mock.ANY)])

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_attachment_email(self, save_mock):
        """
        Test that a single attachment is included as an attachment in
        notification emails.
        """
        self.post(self._attachment_form_data(num=1, action='escalate'))
        eq_(len(mail.outbox[0].attachments), 1,
            'Review attachment not added to email')
        for attachment in mail.outbox[0].attachments:
            self.assertNotEqual(len(attachment), 0, '0-length attachment')
        eq_(save_mock.call_args_list,
            [mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.txt'), mock.ANY)])

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_attachment_email_multiple(self, save_mock):
        """
        Test that mutliple attachments are included as attachments in
        notification emails.
        """
        self.post(self._attachment_form_data(num=2, action='reject'))
        eq_(len(mail.outbox[0].attachments), 2,
            'Review attachments not added to email')
        eq_(save_mock.call_args_list,
            [mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.txt'), mock.ANY),
             mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.jpg'), mock.ANY)])

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_attachment_email_escalate(self, save_mock):
        """
        Test that attachments are included as attachments in an `escalate`
        review, which uses a different mechanism for notification email
        sending.
        """
        self.post(self._attachment_form_data(num=1, action='escalate'))
        eq_(len(mail.outbox[0].attachments), 1,
            'Review attachment not added to email')
        eq_(save_mock.call_args_list,
            [mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.txt'), mock.ANY)])

    @override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
    @mock.patch('amo.utils.LocalFileStorage.save')
    def test_attachment_email_requestinfo(self, save_mock):
        """
        Test that attachments are included as attachments in an `info` review,
        which uses a different mechanism for notification email sending.
        """
        self.post(self._attachment_form_data(num=1, action='info'))
        eq_(len(mail.outbox[0].attachments), 1,
            'Review attachment not added to email')
        eq_(save_mock.call_args_list,
            [mock.call(os.path.join(ATTACHMENTS_DIR, 'bacon.txt'), mock.ANY)])

    def test_idn_app_domain(self):
        response = self.client.get(self.url)
        assert not 'IDN domain!' in response.content

        self.get_app().update(app_domain=u'http://www.allïzom.org')
        response = self.client.get(self.url)
        assert 'IDN domain!' in response.content


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
    fixtures = fixture('user_999', 'user_admin', 'group_admin',
                       'user_admin_group')

    def setUp(self):
        self.app = app_factory()
        self.app.abuse_reports.create(message='eff')
        self.app.abuse_reports.create(message='yeah', reporter_id=999)
        # Make a user abuse report to make sure it doesn't show up.
        AbuseReport.objects.create(message='hey now', user_id=999)

    def test_abuse_reports_list(self):
        self.login('admin@mozilla.com')
        res = self.client.get(reverse('reviewers.apps.review.abuse',
                                      args=[self.app.app_slug]))
        eq_(res.status_code, 200)
        # We see the two abuse reports created in setUp.
        reports = res.context['reports']
        self.assertSetEqual([r.message for r in reports], [u'eff', u'yeah'])


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


class TestGetSigned(BasePackagedAppTest, amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999', 'user_editor',
                       'user_editor_group', 'group_editor')

    def setUp(self):
        super(TestGetSigned, self).setUp()
        self.url = reverse('reviewers.signed', args=[self.app.app_slug,
                                                     self.version.pk])
        self.login('editor@mozilla.com')

    def test_not_logged_in(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_not_reviewer(self):
        self.client.logout()
        self.login('regular@mozilla.com')
        eq_(self.client.get(self.url).status_code, 403)

    @mock.patch('lib.crypto.packaged.sign')
    def test_reviewer_sign_arguments(self, sign_mock):
        self.setup_files()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        sign_mock.assert_called_with(self.version.pk, reviewer=True)

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
    fixtures = fixture('user_editor', 'user_editor_group', 'group_editor',
                       'user_999', 'webapp_337141')

    def setUp(self):
        super(TestMiniManifestView, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        self.version = self.app.versions.latest()
        self.file = self.version.all_files[0]
        self.file.update(filename='mozball.zip')
        self.url = reverse('reviewers.mini_manifest', args=[self.app.id,
                                                            self.version.pk])
        self.login('editor@mozilla.com')

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
        manifest = self.app.get_manifest_json(self.file)

        res = self.client.get(self.url)
        eq_(res['Content-type'],
            'application/x-web-app-manifest+json; charset=utf-8')
        data = json.loads(res.content)
        eq_(data['name'], manifest['name'])
        eq_(data['developer']['name'], 'Mozilla Marketplace')
        eq_(data['package_path'],
            absolutify(reverse('reviewers.signed',
                       args=[self.app.app_slug, self.version.id])))

    def test_rejected(self):
        # Rejected sets file.status to DISABLED and moves to a guarded path.
        self.setup_files()
        self.app.update(status=amo.STATUS_REJECTED)
        self.file.update(status=amo.STATUS_DISABLED)
        manifest = self.app.get_manifest_json(self.file)

        res = self.client.get(self.url)
        eq_(res['Content-type'],
            'application/x-web-app-manifest+json; charset=utf-8')
        data = json.loads(res.content)
        eq_(data['name'], manifest['name'])
        eq_(data['developer']['name'], 'Mozilla Marketplace')
        eq_(data['package_path'],
            absolutify(reverse('reviewers.signed',
                       args=[self.app.app_slug,
                             self.version.id])))

    def test_minifest_name_matches_manifest_name(self):
        self.setup_files()
        self.app.name = 'XXX'
        self.app.save()
        manifest = self.app.get_manifest_json(self.file)

        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['name'], manifest['name'])


class TestReviewersScores(AppReviewerTest, AccessMixin):
    fixtures = fixture('group_editor', 'user_editor', 'user_editor_group',
                       'user_999')

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


class TestQueueSort(AppReviewerTest):
    fixtures = ['base/users']

    def setUp(self):
        """Create and set up apps for some filtering fun."""
        self.apps = [app_factory(name='Lillard',
                                 status=amo.STATUS_PENDING,
                                 is_packaged=False,
                                 version_kw={'version': '1.0'},
                                 file_kw={'status': amo.STATUS_PENDING},
                                 admin_review=True,
                                 premium_type=amo.ADDON_FREE),
                     app_factory(name='Batum',
                                 status=amo.STATUS_PENDING,
                                 is_packaged=True,
                                 version_kw={'version': '1.0',
                                             'has_editor_comment': True,
                                             'has_info_request': True},
                                 file_kw={'status': amo.STATUS_PENDING},
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

    def test_do_sort_webapp(self):
        """
        Test that apps are sorted in order specified in GET params.
        """
        rf = RequestFactory()
        qs = Webapp.objects.no_cache().all()

        # Test apps are sorted by created/asc by default.
        r = rf.get(self.url, {'sort': 'invalidsort', 'order': 'dontcare'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[1], self.apps[0]])

        # Test sorting by created, descending.
        r = rf.get(self.url, {'sort': 'created', 'order': 'desc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[0], self.apps[1]])

        # Test sorting by app name.
        r = rf.get(self.url, {'sort': 'name', 'order': 'asc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[1], self.apps[0]])

        r = rf.get(self.url, {'sort': 'name', 'order': 'desc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[0], self.apps[1]])

        # By abuse reports.
        AbuseReport.objects.create(addon=self.apps[1])
        r = rf.get(self.url, {'sort': 'num_abuse_reports',
                              'order': 'asc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[0], self.apps[1]])

        r = rf.get(self.url, {'sort': 'num_abuse_reports',
                              'order': 'desc'})
        sorted_qs = _do_sort(r, qs)
        eq_(list(sorted_qs), [self.apps[1], self.apps[0]])

    def test_do_sort_version_nom(self):
        """Tests version nomination sort order."""
        url = reverse('reviewers.apps.queue_pending')
        user = UserProfile.objects.get(username='admin')

        version_0 = self.apps[0].versions.get()
        version_0.update(nomination=days_ago(1))
        version_1 = self.apps[1].versions.get()
        version_1.update(nomination=days_ago(2))

        # Throw in some disabled versions, they shouldn't affect order.
        version_factory({'status': amo.STATUS_DISABLED}, addon=self.apps[0],
                        nomination=days_ago(10))
        version_factory({'status': amo.STATUS_DISABLED}, addon=self.apps[1],
                        nomination=days_ago(1))
        version_factory({'status': amo.STATUS_DISABLED}, addon=self.apps[1],
                        nomination=days_ago(20))

        req = amo.tests.req_factory_factory(
            url, user=user, data={'sort': 'nomination'})
        res = queue_apps(req)
        doc = pq(res.content)
        eq_(doc('tbody tr')[0].get('data-addon'), str(version_1.addon.id))
        eq_(doc('tbody tr')[1].get('data-addon'), str(version_0.addon.id))

        req = amo.tests.req_factory_factory(
            url, user=user, data={'sort': 'nomination', 'order': 'desc'})
        res = queue_apps(req)
        doc = pq(res.content)
        eq_(doc('tbody tr')[0].get('data-addon'), str(version_0.addon.id))
        eq_(doc('tbody tr')[1].get('data-addon'), str(version_1.addon.id))

    def test_do_sort_queue_object(self):
        """Tests sorting queue object."""
        rf = RequestFactory()
        url = reverse('reviewers.apps.queue_rereview')

        earlier_rrq = RereviewQueue.objects.create(addon=self.apps[0])
        later_rrq = RereviewQueue.objects.create(addon=self.apps[1])
        later_rrq.created += datetime.timedelta(days=1)
        later_rrq.save()

        request = rf.get(url, {'sort': 'created'})
        apps = _do_sort(request, RereviewQueue.objects.all())

        # Assert the order that RereviewQueue objects were created is
        # maintained.
        eq_([earlier_rrq.addon, later_rrq.addon], list(apps))

        request = rf.get(url, {'sort': 'created', 'order': 'desc'})
        apps = _do_sort(request, RereviewQueue.objects.all())
        eq_([later_rrq.addon, earlier_rrq.addon], list(apps))

        request = rf.get(url, {'sort': 'name', 'order': 'asc'})
        apps = _do_sort(request, RereviewQueue.objects.all())
        eq_([later_rrq.addon, earlier_rrq.addon], list(apps))

        request = rf.get(url, {'sort': 'name', 'order': 'desc'})
        apps = _do_sort(request, RereviewQueue.objects.all())
        eq_([earlier_rrq.addon, later_rrq.addon], list(apps))


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


@override_settings(REVIEWER_ATTACHMENTS_PATH=ATTACHMENTS_DIR)
class TestAttachmentDownload(amo.tests.TestCase):
    fixtures = ['data/user_editor', 'data/user_editor_group',
                'data/group_editor', 'data/user_999',
                'webapps/337141-steamcube']

    def _attachment(self, log):
        return ActivityLogAttachment.objects.create(activity_log=log,
                                                    filepath='bacon.jpg',
                                                    mimetype='image/jpeg')

    def _response(self, params={}, **kwargs):
        url = self.ala.get_absolute_url()
        return self.client.get(url, params, **kwargs)

    def setUp(self):
        editor = UserProfile.objects.get(user__pk=5497308)
        self.app = Webapp.objects.get(pk=337141)
        self.version = self.app.latest_version
        self.al = amo.log(amo.LOG.COMMENT_VERSION, self.app,
                          self.version, user=editor)
        self.ala = self._attachment(self.al)

    def test_permissions_editor(self):
        self.client.login(username='editor@mozilla.com', password='password')
        response = self._response()
        eq_(response.status_code, 200, 'Editor cannot access attachment')

    def test_permissions_regular(self):
        self.client.login(username='regular@mozilla.com', password='password')
        response = self._response()
        eq_(response.status_code, 403, 'Regular user can access attachment')

    def test_headers(self):
        self.client.login(username='editor@mozilla.com', password='password')
        response = self._response()
        eq_(response._headers['content-type'][1], 'application/force-download',
            'Attachment not served as application/force-download')
        eq_(response._headers['content-disposition'][1],
            'attachment; filename=bacon.jpg',
            'Attachment not served with correct Content-Disposition header')
        eq_(response._headers['content-length'][1], '130737',
            'Attachment not served with correct Content-Length header')


class TestLeaderboard(AppReviewerTest):
    fixtures = ['base/users']

    def setUp(self):
        self.url = reverse('reviewers.leaderboard')

        self.user = UserProfile.objects.get(email='editor@mozilla.com')
        self.login_as_editor()
        amo.set_user(self.user)

    def _award_points(self, user, score):
        ReviewerScore.objects.create(user=user, note_key=amo.REVIEWED_MANUAL,
                                     score=score, note='Thing.')

    def test_leaderboard_ranks(self):
        users = (self.user,
                 UserProfile.objects.get(email='regular@mozilla.com'),
                 UserProfile.objects.get(email='clouserw@gmail.com'))

        self._award_points(users[0], amo.REVIEWED_LEVELS[0]['points'] - 1)
        self._award_points(users[1], amo.REVIEWED_LEVELS[0]['points'] + 1)
        self._award_points(users[2], amo.REVIEWED_LEVELS[0]['points'] + 2)

        def get_cells():
            doc = pq(self.client.get(self.url).content.decode('utf-8'))

            cells = doc('#leaderboard > tbody > tr > .name, '
                        '#leaderboard > tbody > tr > .level')

            return [cells.eq(i).text() for i in range(0, cells.length)]

        eq_(get_cells(),
            [users[2].display_name,
             users[1].display_name,
             amo.REVIEWED_LEVELS[0]['name'],
             users[0].display_name])

        self._award_points(users[0], 1)

        eq_(get_cells(),
            [users[2].display_name,
             users[1].display_name,
             users[0].display_name,
             amo.REVIEWED_LEVELS[0]['name']])

        self._award_points(users[0], -1)
        self._award_points(users[2], (amo.REVIEWED_LEVELS[1]['points'] -
                                      amo.REVIEWED_LEVELS[0]['points']))

        eq_(get_cells(),
            [users[2].display_name,
             amo.REVIEWED_LEVELS[1]['name'],
             users[1].display_name,
             amo.REVIEWED_LEVELS[0]['name'],
             users[0].display_name])


class TestReviewPage(amo.tests.TestCase):
    fixtures = fixture('user_editor', 'user_editor_group', 'group_editor')

    def setUp(self):
        self.create_switch('iarc')
        self.app = app_factory(status=amo.STATUS_PENDING)
        self.reviewer = UserProfile.objects.get()
        self.url = reverse('reviewers.apps.review', args=[self.app.app_slug])

    def test_iarc_ratingless_disable_approve_btn(self):
        self.app.update(status=amo.STATUS_NULL)
        req = req_factory_factory(self.url, user=self.reviewer)
        res = app_review(req, app_slug=self.app.app_slug)
        doc = pq(res.content)
        assert (doc('#review-actions input[value=public]')
                .parents('li').hasClass('disabled'))
        assert not (doc('#review-actions input[value=reject]')
                    .parents('li').hasClass('disabled'))

    def test_iarc_content_ratings(self):
        for body in [mkt.ratingsbodies.CLASSIND.id, mkt.ratingsbodies.USK.id]:
            self.app.content_ratings.create(ratings_body=body, rating=0)
        req = req_factory_factory(self.url, user=self.reviewer)
        res = app_review(req, app_slug=self.app.app_slug)
        doc = pq(res.content)
        eq_(doc('.content-rating').length, 2)
