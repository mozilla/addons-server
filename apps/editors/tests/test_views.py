# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import json
import time
import urlparse

from django.conf import settings
from django.core import mail
from django.utils.datastructures import SortedDict

from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.utils import urlparams
from amo.tests import app_factory, check_links, formset, initial
from abuse.models import AbuseReport
from access.models import Group, GroupUser
from addons.models import Addon, AddonDependency, AddonUser
from applications.models import Application
from devhub.models import ActivityLog
from editors.models import EditorSubscription, EventLog
from files.models import File
import reviews
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from versions.models import Version, AppVersion, ApplicationsVersions
from zadmin.models import get_config, set_config

from . test_models import create_addon_file


class EditorTest(amo.tests.TestCase):
    fixtures = ['base/users', 'base/platforms', 'base/approvals',
                'editors/pending-queue']

    def login_as_admin(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def login_as_editor(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def make_review(self, username='a'):
        u = UserProfile.objects.create(username=username)
        a = Addon.objects.create(name='yermom', type=amo.ADDON_EXTENSION)
        return Review.objects.create(user=u, addon=a)

    def _test_breadcrumbs(self, expected=[]):
        r = self.client.get(self.url)
        expected.insert(0, ('Editor Tools', reverse('editors.home')))
        check_links(expected, pq(r.content)('#breadcrumbs li'), verify=False)


class TestEventLog(EditorTest):

    def setUp(self):
        self.login_as_editor()
        self.url = reverse('editors.eventlog')
        amo.set_user(UserProfile.objects.get(username='editor'))

    def test_log(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_start_filter(self):
        r = self.client.get(self.url, dict(start='2011-01-01'))
        eq_(r.status_code, 200)

    def test_enddate_filter(self):
        """
        Make sure that if our end date is 1/1/2011, that we include items from
        1/1/2011.  To not do as such would be dishonorable.
        """
        review = self.make_review(username='b')
        amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon,
                created=datetime(2011, 1, 1))

        r = self.client.get(self.url, dict(end='2011-01-01'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('tbody td').eq(0).text(), 'Jan 1, 2011 12:00:00 AM')

    def test_action_filter(self):
        """
        Based on setup we should see only two items if we filter for deleted
        reviews.
        """
        review = self.make_review()
        for i in xrange(2):
            amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon)
            amo.log(amo.LOG.DELETE_REVIEW, review.id, review.addon)
        r = self.client.get(self.url, dict(filter='deleted'))
        eq_(pq(r.content)('tbody tr').length, 2)

    def test_no_results(self):
        r = self.client.get(self.url, dict(end='2004-01-01'))
        assert '"no-results"' in r.content, 'Expected no results to be found.'

    def test_breadcrumbs(self):
        self._test_breadcrumbs([('Moderated Review Log', None)])


class TestEventLogDetail(TestEventLog):

    def test_me(self):
        review = self.make_review()
        amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon)
        id = ActivityLog.objects.editor_events()[0].id
        r = self.client.get(reverse('editors.eventlog.detail', args=[id]))
        eq_(r.status_code, 200)


class TestReviewLog(EditorTest):
    fixtures = EditorTest.fixtures + ['base/addon_3615', 'base/platforms']

    def setUp(self):
        self.login_as_editor()
        self.url = reverse('editors.reviewlog')

    def get_user(self):
        return UserProfile.objects.all()[0]

    def make_approvals(self):
        for addon in Addon.objects.all():
            amo.log(amo.LOG.REJECT_VERSION, addon, addon.current_version,
                    user=self.get_user(), details={'comments': 'youwin'})

    def make_an_approval(self, action, comment='youwin', username=None,
                         addon=None):
        if username:
            user = UserProfile.objects.get(username=username)
        else:
            user = self.get_user()
        if not addon:
            addon = Addon.objects.all()[0]
        amo.log(action, addon, addon.current_version, user=user,
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
        a = Addon.objects.all()[0]
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
        addon = Addon.objects.all()[0]
        r = self.client.get(self.url, dict(search=addon.name))
        eq_(r.status_code, 200)
        tr = pq(r.content)('#log-listing tr[data-addonid="%s"]' % addon.id)
        eq_(tr.length, 1)
        eq_(tr.siblings('.comments').text(), 'youwin')

    def test_search_addon_doesnt_exist(self):
        """Search by add-on name, with no results."""
        self.make_approvals()
        r = self.client.get(self.url, dict(search='xxx'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    def test_breadcrumbs(self):
        self._test_breadcrumbs([('Add-on Review Log', None)])

    @patch('devhub.models.ActivityLog.arguments', new=Mock)
    def test_addon_missing(self):
        self.make_approvals()
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td').eq(1).text(),
            'Add-on has been deleted.')

    def test_request_info_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_INFORMATION)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td a').eq(1).text(),
            'needs more information')

    def test_super_review_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#log-listing tr td a').eq(1).text(),
            'needs super review')


class TestHome(EditorTest):
    fixtures = EditorTest.fixtures + ['base/addon_3615', 'base/platforms']

    def setUp(self):
        self.login_as_editor()
        self.url = reverse('editors.home')
        self.user = UserProfile.objects.get(id=5497308)
        self.user.display_name = 'editor'
        self.user.save()
        amo.set_user(self.user)

    def approve_reviews(self):
        for addon in Addon.objects.all():
            amo.set_user(self.user)
            amo.log(amo.LOG['APPROVE_VERSION'], addon, addon.current_version)

    def test_approved_review(self):
        review = self.make_review()
        amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon,
                details=dict(addon_name='test', addon_id=review.addon.pk,
                is_flagged=True))
        r = self.client.get(self.url)
        row = pq(r.content)('.row')
        assert 'approved' in row.text(), (
            'Expected review to be approved by editor')
        assert row('a[href*=yermom]'), 'Expected links to approved addon'

    def test_deleted_review(self):
        review = self.make_review()
        amo.log(amo.LOG.DELETE_REVIEW, review.id, review.addon,
                details=dict(addon_name='test', addon_id=review.addon.pk,
                             is_flagged=True))
        doc = pq(self.client.get(self.url).content)

        eq_(doc('.row').eq(0).text().strip().split('.')[0],
            'editor deleted %d for yermom ' % review.id)

        al_id = ActivityLog.objects.all()[0].id
        url = reverse('editors.eventlog.detail', args=[al_id])
        doc = pq(self.client.get(url).content)

        dts, dds = doc('dt'), doc('dd')
        expected = [
            ('is_flagged', 'True'),
            ('addon_id', str(review.addon.pk)),
            ('addon_name', 'test'),
        ]
        for idx, pair in enumerate(expected):
            dt, dd = pair
            eq_(dts.eq(idx).text(), dt)
            eq_(dds.eq(idx).text(), dd)

    def test_stats_total(self):
        self.approve_reviews()

        doc = pq(self.client.get(self.url).content)

        cols = doc('#editors-stats .editor-stats-table:eq(1)').find('td')
        eq_(cols.eq(0).text(), self.user.display_name)
        eq_(int(cols.eq(1).text()), 2, 'Approval count should be 2')

    def test_stats_monthly(self):
        self.approve_reviews()

        doc = pq(self.client.get(self.url).content)

        cols = doc('#editors-stats .editor-stats-table:eq(1)').find('td')
        eq_(cols.eq(0).text(), self.user.display_name)
        eq_(int(cols.eq(1).text()), 2, 'Approval count should be 2')

    def test_new_editors(self):
        EventLog(type='admin', action='group_addmember', changed_id=2,
                 added=self.user.id, user=self.user).save()

        doc = pq(self.client.get(self.url).content)

        anchors = doc('#editors-stats .editor-stats-table:eq(2)').find('td a')
        eq_(anchors.eq(0).text(), self.user.display_name)


class QueueTest(EditorTest):
    fixtures = ['base/users']

    def setUp(self):
        super(QueueTest, self).setUp()
        self.login_as_editor()
        self.url = reverse('editors.queue_pending')
        self.addons = SortedDict()
        self.expected_addons = []

    def generate_files(self, subset=[]):
        files = SortedDict([
            ('Pending One', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_PUBLIC,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Pending Two', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_PUBLIC,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Nominated One', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Nominated Two', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_LITE_AND_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Prelim One', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_LITE,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Prelim Two', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_UNREVIEWED,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Public', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_PUBLIC,
                'file_status': amo.STATUS_LISTED,
            }),
        ])
        results = {}
        for name, attrs in files.iteritems():
            if not subset or name in subset:
                results[name] = self.addon_file(name, **attrs)
        return results

    def generate_file(self, name):
        return self.generate_files([name])[name]

    def get_review_data(self):
        # Format: (Created n days ago,
        #          percentages of [< 5, 5-10, >10],
        #          how many are under 7 days?)
        return ((1, (0, 0, 100), 2),
                (8, (0, 50, 50), 1),
                (11, (50, 0, 50), 1))

    def addon_file(self, *args, **kw):
        a = create_addon_file(*args, **kw)
        name = args[0]  # Add-on name.
        self.addons[name] = a['addon']
        # If this is an add-on we expect to be in the queue, then add it.
        if name in getattr(self, 'expected_names', []):
            self.expected_addons.append(a['addon'])
        return a['addon']

    def get_queue(self, addon):
        version = addon.latest_version
        eq_(version.current_queue.objects.filter(id=addon.id).count(), 1)

    def _test_get_queue(self):
        self.generate_files()
        for addon in self.expected_addons:
            self.get_queue(addon)

    def _test_queue_count(self, eq, name, count):
        self.generate_files()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        a = pq(r.content)('.tabnav li a:eq(%s)' % eq)
        eq_(a.text(), '%s (%s)' % (name, count))
        eq_(a.attr('href'), self.url)

    def _test_results(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        expected = []
        for idx, addon in enumerate(self.expected_addons):
            name = '%s %s' % (unicode(addon.name),
                              addon.current_version.version)
            url = reverse('editors.review', args=[addon.slug])
            expected.append((name, urlparams(url, num=idx + 1)))
        check_links(expected,
            pq(r.content)('#addon-queue tr.addon-row td a:not(.app-icon)'),
            verify=False)


class TestQueueBasics(QueueTest):

    def test_only_viewable_by_editor(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(self.url)
        eq_(r.status_code, 403)

    def test_invalid_page(self):
        r = self.client.get(self.url, {'page': 999})
        eq_(r.status_code, 200)
        eq_(r.context['page'].number, 1)

    def test_invalid_per_page(self):
        r = self.client.get(self.url, {'per_page': '<garbage>'})
        # No exceptions:
        eq_(r.status_code, 200)

    def test_redirect_to_review(self):
        self.generate_files(['Pending One', 'Pending Two'])
        r = self.client.get(self.url, {'num': 2})
        slug = self.addons['Pending Two'].slug
        url = reverse('editors.review', args=[slug])
        self.assertRedirects(r, url + '?num=2')

    def test_invalid_review_ignored(self):
        r = self.client.get(self.url, {'num': 1})
        eq_(r.status_code, 200)

    def test_garbage_review_num_ignored(self):
        r = self.client.get(self.url, {'num': 'not-a-number'})
        eq_(r.status_code, 200)

    def test_grid_headers(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        expected = [
            'Addon',
            'Type',
            'Waiting Time',
            'Flags',
            'Applications',
            'Platforms',
            'Additional',
        ]
        eq_([pq(th).text() for th in doc('#addon-queue tr th')[1:]],
            expected)

    def test_grid_headers_sort_after_search(self):
        params = dict(searching=['True'],
                      text_query=['abc'],
                      addon_type_ids=['2'],
                      sort=['addon_type_id'])
        r = self.client.get(self.url, params)
        eq_(r.status_code, 200)
        tr = pq(r.content)('#addon-queue tr')
        sorts = {
            # Column index => sort.
            1: 'addon_name',        # Add-on.
            2: '-addon_type_id',    # Type.
            3: 'waiting_time_min',  # Waiting Time.
        }
        for idx, sort in sorts.iteritems():
            # Get column link.
            a = tr('th:eq(%s)' % idx).find('a')
            # Update expected GET parameters with sort type.
            params.update(sort=[sort])
            # Parse querystring of link to make sure `sort` type is correct.
            eq_(urlparse.parse_qs(a.attr('href').split('?')[1]), params)

    def test_no_results(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.queue-outer .no-results').length, 1)

    def test_no_paginator_when_on_single_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.pagination').length, 0)

    def test_paginator_when_many_pages(self):
        # 'Pending One' and 'Pending Two' should be the only add-ons in
        # the pending queue, but we'll generate them all for good measure.
        self.generate_files()

        r = self.client.get(self.url, {'per_page': 1})
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.data-grid-top .num-results').text(),
            u'Results 1 \u2013 1 of 2')
        eq_(doc('.data-grid-bottom .num-results').text(),
            u'Results 1 \u2013 1 of 2')

    def test_navbar_queue_counts(self):
        self.generate_files()

        r = self.client.get(reverse('editors.home'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#navbar li.top ul').eq(0).text(),
            'Fast Track (0) Full Reviews (2) Pending Updates (2) '
            'Preliminary Reviews (2) Moderated Reviews (0)')

    def test_legacy_queue_sort(self):
        sorts = (
            ['age', 'Waiting Time'],
            ['name', 'Addon'],
            ['type', 'Type'],
        )
        for key, text in sorts:
            r = self.client.get(self.url, {'sort': key})
            eq_(r.status_code, 200)
            eq_(pq(r.content)('th.ordered a').text(), text)

    def test_full_reviews_bar(self):
        self.generate_files()
        version = self.addons['Nominated Two'].versions.all()[0]

        style = lambda w: 'width:%s%%' % (float(w) if w > 0 else 0)

        for days, widths, under_7 in self.get_review_data():
            new_nomination = datetime.now() - timedelta(days=days)
            version.update(nomination=new_nomination)

            r = self.client.get(reverse('editors.home'))

            doc = pq(r.content)
            div = doc('#editors-stats-charts .editor-stats-table:eq(0)')

            eq_(div('.waiting_old').attr('style'), style(widths[0]))
            eq_(div('.waiting_med').attr('style'), style(widths[1]))
            eq_(div('.waiting_new').attr('style'), style(widths[2]))

            eq_(div.children('div:eq(0)').text().split()[0], str(under_7))

    def test_pending_bar(self):
        self.generate_files()

        addon = self.addons['Pending One']
        for data in self.get_review_data():
            self.check_bar(addon, eq=1, data=data, reset_status=True)

    def test_prelim_bar(self):
        self.generate_files()

        addon = self.addons['Prelim One']
        for data in self.get_review_data():
            self.check_bar(addon, eq=2, data=data)

    def check_bar(self, addon, eq, data, reset_status=False):
        # `eq` is the table number (0, 1 or 2).
        style = lambda w: 'width:%s%%' % (float(w) if w > 0 else 0)

        days, widths, under_7 = data

        f = addon.versions.all()[0].all_files[0]
        f.update(created=datetime.now() - timedelta(days=days))

        # For pending, we must reset the add-on status after saving version.
        if reset_status:
            addon.update(status=amo.STATUS_PUBLIC)

        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)

        div = doc('#editors-stats-charts .editor-stats-table:eq(%s)' % eq)

        eq_(div('.waiting_old').attr('style'), style(widths[0]))
        eq_(div('.waiting_med').attr('style'), style(widths[1]))
        eq_(div('.waiting_new').attr('style'), style(widths[2]))

        eq_(div.children('div:eq(0)').text().split()[0], str(under_7))

    def test_flags_jetpack(self):
        ad = create_addon_file('Jetpack', '0.1', amo.STATUS_NOMINATED,
                               amo.STATUS_UNREVIEWED)
        ad_file = ad['version'].files.all()[0]
        ad_file.update(jetpack_version=1.2)

        r = self.client.get(reverse('editors.queue_nominated'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        eq_(rows.length, 1)
        eq_(rows.attr('data-addon'), str(ad['addon'].id))
        eq_(rows.find('td').eq(1).text(), 'Jetpack 0.1')
        eq_(rows.find('.ed-sprite-jetpack').length, 1)
        eq_(rows.find('.ed-sprite-restartless').length, 0)

    def test_flags_restartless(self):
        ad = create_addon_file('Restartless', '0.1', amo.STATUS_NOMINATED,
                               amo.STATUS_UNREVIEWED)
        ad_file = ad['version'].files.all()[0]
        ad_file.update(no_restart=True)

        r = self.client.get(reverse('editors.queue_nominated'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        eq_(rows.length, 1)
        eq_(rows.attr('data-addon'), str(ad['addon'].id))
        eq_(rows.find('td').eq(1).text(), 'Restartless 0.1')
        eq_(rows.find('.ed-sprite-jetpack').length, 0)
        eq_(rows.find('.ed-sprite-restartless').length, 1)

    def test_flags_restartless_and_jetpack(self):
        ad = create_addon_file('Restartless Jetpack', '0.1',
                               amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        ad_file = ad['version'].files.all()[0]
        ad_file.update(jetpack_version=1.2, no_restart=True)

        r = self.client.get(reverse('editors.queue_nominated'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        eq_(rows.length, 1)
        eq_(rows.attr('data-addon'), str(ad['addon'].id))
        eq_(rows.find('td').eq(1).text(), 'Restartless Jetpack 0.1')

        # Show only jetpack if it's both.
        eq_(rows.find('.ed-sprite-jetpack').length, 1)
        eq_(rows.find('.ed-sprite-restartless').length, 0)

    def test_flags_premium(self):
        ad = create_addon_file('Premium add-on', '0.1', amo.STATUS_NOMINATED,
                               amo.STATUS_UNREVIEWED)
        for type_ in amo.ADDON_PREMIUMS:
            ad['addon'].update(premium_type=type_)

            r = self.client.get(reverse('editors.queue_nominated'))

            rows = pq(r.content)('#addon-queue tr.addon-row')
            eq_(rows.length, 1)
            eq_(rows.attr('data-addon'), str(ad['addon'].id))
            eq_(rows.find('td').eq(1).text(), 'Premium add-on 0.1')
            eq_(rows.find('.ed-sprite-premium').length, 1)


class TestPendingQueue(QueueTest):

    def setUp(self):
        super(TestPendingQueue, self).setUp()
        # These should be the only ones present in the queue.
        self.expected_names = ['Pending One', 'Pending Two']
        self.url = reverse('editors.queue_pending')

    def test_results(self):
        # `generate_files` happens within this test.
        self._test_results()

    def test_breadcrumbs(self):
        self._test_breadcrumbs([('Pending Updates', None)])

    def test_queue_count(self):
        # `generate_files` happens within this test.
        self._test_queue_count(2, 'Pending Updates', 2)

    def test_get_queue(self):
        # `generate_files` happens within this test.
        self._test_get_queue()


class TestNominatedQueue(QueueTest):

    def setUp(self):
        super(TestNominatedQueue, self).setUp()
        self.expected_names = ['Nominated One', 'Nominated Two']
        self.url = reverse('editors.queue_nominated')

    def test_results(self):
        self._test_results()

    def test_results_two_versions(self):
        self.generate_files()

        v1 = self.addons['Nominated One'].versions.all()[0]
        v2 = self.addons['Nominated Two'].versions.all()[0]
        a1, a2 = v1.addon, v2.addon
        f = v2.all_files[0]

        original_nomination = v2.nomination
        v2.nomination = v2.nomination - timedelta(days=1)
        v2.save()

        # Create another version, v0.2.
        v2.pk = None
        v2.nomination = original_nomination
        v2.version = '0.2'
        v2.save()

        # Associate v0.2 it with a file.
        f.pk = None
        f.version = v2
        f.save()

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        expected = [
            ('Nominated One 0.1',
             reverse('editors.review', args=[a1.slug]) + '?num=1'),
            ('Nominated Two 0.2',
             reverse('editors.review', args=[a2.slug]) + '?num=2'),
        ]
        check_links(expected,
            pq(r.content)('#addon-queue tr.addon-row td a:not(.app-icon)'),
            verify=False)

    def test_queue_count(self):
        self._test_queue_count(1, 'Full Reviews', 2)

    def _test_get_queue(self):
        self._test_get_queue()


class TestPreliminaryQueue(QueueTest):

    def setUp(self):
        super(TestPreliminaryQueue, self).setUp()
        # These should be the only ones present.
        self.expected_names = ['Prelim One', 'Prelim Two']
        self.url = reverse('editors.queue_prelim')

    def test_results(self):
        self._test_results()

    def test_breadcrumbs(self):
        self._test_breadcrumbs([('Preliminary Reviews', None)])

    def test_queue_count(self):
        self._test_queue_count(3, 'Preliminary Reviews', 2)

    def _test_get_queue(self):
        self._test_get_queue()


class TestModeratedQueue(QueueTest):
    fixtures = ['base/users', 'base/platforms', 'reviews/dev-reply']

    def setUp(self):
        super(TestModeratedQueue, self).setUp()

        self.url = reverse('editors.queue_moderated')
        url_flag = reverse('addons.reviews.flag', args=['a1865', 218468])

        response = self.client.post(url_flag, {'flag': ReviewFlag.SPAM})
        eq_(response.status_code, 200)

        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.SPAM).count(), 1)
        eq_(Review.objects.filter(editorreview=True).count(), 1)

    def test_results(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('#reviews-flagged')

        rows = doc('.review-flagged:not(.review-saved)')
        eq_(rows.length, 1)
        eq_(rows.find('h3').text(), ": Don't use Firefox 2.0!")

        # Default is "Skip."
        eq_(doc('#id_form-0-action_1:checked').length, 1)

        flagged = doc('.reviews-flagged-reasons span.light').text()
        editor = ReviewFlag.objects.all()[0].user.name
        assert flagged.startswith('Flagged by %s' % editor), (
            'Unexpected text: %s' % flagged)

    def setup_actions(self, action):
        ctx = self.client.get(self.url).context
        fs = initial(ctx['reviews_formset'].forms[0])

        eq_(Review.objects.filter(addon=1865).count(), 2)

        data_formset = formset(fs)
        data_formset['form-0-action'] = action

        r = self.client.post(self.url, data_formset)
        self.assertRedirects(r, self.url)

    def test_skip(self):
        self.setup_actions(reviews.REVIEW_MODERATE_SKIP)

        # Make sure it's still there.
        r = self.client.get(self.url)
        doc = pq(r.content)
        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        eq_(rows.length, 1)

    def get_logs(self, action):
        return ActivityLog.objects.filter(action=action.id)

    def test_remove(self):
        """Make sure the editor tools can delete a review."""
        self.setup_actions(reviews.REVIEW_MODERATE_DELETE)
        logs = self.get_logs(amo.LOG.DELETE_REVIEW)
        eq_(logs.count(), 1)

        # Make sure it's removed from the queue.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#reviews-flagged .no-results').length, 1)

        r = self.client.get(reverse('editors.eventlog'))
        eq_(pq(r.content)('table .more-details').attr('href'),
            reverse('editors.eventlog.detail', args=[logs[0].id]))

        # Make sure it was actually deleted.
        eq_(Review.objects.filter(addon=1865).count(), 1)

    def test_keep(self):
        """Make sure the editor tools can remove flags and keep a review."""
        self.setup_actions(reviews.REVIEW_MODERATE_KEEP)
        logs = self.get_logs(amo.LOG.APPROVE_REVIEW)
        eq_(logs.count(), 1)

        # Make sure it's removed from the queue.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#reviews-flagged .no-results').length, 1)

        review = Review.objects.filter(addon=1865)

        # Make sure it's NOT deleted...
        eq_(review.count(), 2)

        # ...but it's no longer flagged.
        eq_(review.filter(editorreview=1).count(), 0)

    def test_queue_count(self):
        self._test_queue_count(4, 'Moderated Review', 1)

    def test_queue_count_w_webapp_reviews(self):
        Addon.objects.update(type=amo.ADDON_WEBAPP)
        self._test_queue_count(4, 'Moderated Reviews', 0)

    def test_queue_no_webapp_reviews(self):
        app = app_factory()
        user = UserProfile.objects.get(email='clouserw@gmail.com')
        review = Review.objects.create(addon=app, editorreview=True, user=user,
                                       body='bad', rating=4)
        ReviewFlag.objects.create(review=review, flag=ReviewFlag.SPAM,
                                  user=user)
        res = self.client.get(self.url)
        assert review not in res.context['page'].object_list, (
            u'Found a review for a webapp we should not have.')

    def test_breadcrumbs(self):
        self._test_breadcrumbs([('Moderated Reviews', None)])

    def test_no_reviews(self):
        Review.objects.all().delete()

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('#reviews-flagged')

        eq_(doc('.no-results').length, 1)
        eq_(doc('.review-saved button').length, 1)  # Show only one button.


class TestPerformance(QueueTest):
    fixtures = ['base/users', 'editors/pending-queue', 'base/addon_3615']

    """Test the page at /editors/performance."""

    def setUpEditor(self):
        self.login_as_editor()
        amo.set_user(UserProfile.objects.get(username='editor'))
        self.create_logs()

    def setUpAdmin(self):
        self.login_as_admin()
        amo.set_user(UserProfile.objects.get(username='admin'))
        self.create_logs()

    def get_url(self, args=[]):
        return reverse('editors.performance', args=args)

    def create_logs(self):
        addon = Addon.objects.all()[0]
        version = addon.versions.all()[0]
        for i in amo.LOG_REVIEW_QUEUE:
            amo.log(amo.LOG_BY_ID[i], addon, version)

    def _test_chart(self):
        r = self.client.get(self.get_url())
        eq_(r.status_code, 200)
        doc = pq(r.content)

        # The ' - 1' is to account for REQUEST_VERSION not being displayed.
        num = len(amo.LOG_REVIEW_QUEUE) - 1
        label = datetime.now().strftime('%Y-%m')
        data = {label: {u'teamcount': num, u'teamavg': u'%s.0' % num,
                        u'usercount': num, u'teamamt': 1,
                        u'label': datetime.now().strftime('%b %Y')}}

        eq_(json.loads(doc('#monthly').attr('data-chart')), data)

    def test_performance_chart_editor(self):
        self.setUpEditor()
        self._test_chart()

    def test_performance_chart_as_admin(self):
        self.setUpAdmin()
        self._test_chart()

    def test_performance_other_user_as_admin(self):
        self.setUpAdmin()

        r = self.client.get(self.get_url([10482]))
        doc = pq(r.content)

        eq_(doc('#select_user').length, 1)  # Let them choose editors.
        options = doc('#select_user option')
        eq_(options.length, 3)
        eq_(options.eq(2).val(), '4043307')

        assert 'clouserw' in doc('#reviews_user').text()

    def test_performance_other_user_not_admin(self):
        self.setUpEditor()

        r = self.client.get(self.get_url([10482]))
        doc = pq(r.content)

        eq_(doc('#select_user').length, 0)  # Don't let them choose editors.
        eq_(doc('#reviews_user').text(), 'Your Reviews')


class SearchTest(EditorTest):

    def setUp(self):
        self.login_as_editor()

    def named_addons(self, request):
        return [r.data.addon_name for r in request.context['page'].object_list]

    def search(self, *args, **kw):
        r = self.client.get(self.url, kw)
        eq_(r.status_code, 200)
        eq_(r.context['search_form'].errors.as_text(), '')
        return r


class TestQueueSearch(SearchTest):
    fixtures = ['base/users', 'base/apps', 'base/appversion']

    def setUp(self):
        super(TestQueueSearch, self).setUp()
        self.url = reverse('editors.queue_nominated')

    def generate_files(self, subset=[]):
        files = SortedDict([
            ('Not Admin Reviewed', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
            }),
            ('Admin Reviewed', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
                'admin_review': True,
            }),
            ('Justin Bieber Theme', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
                'addon_type': amo.ADDON_THEME,
            }),
            ('Justin Bieber Search Bar', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
                'addon_type': amo.ADDON_SEARCH,
            }),
            ('Bieber For Mobile', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
                'application': amo.MOBILE,
            }),
            ('Linux Widget', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
                'platform': amo.PLATFORM_LINUX,
            }),
            ('Mac Widget', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_UNREVIEWED,
                'platform': amo.PLATFORM_MAC,
            }),
        ])
        results = {}
        for name, attrs in files.iteritems():
            if not subset or name in subset:
                results[name] = create_addon_file(name, **attrs)
        return results

    def generate_file(self, name):
        return self.generate_files([name])[name]

    def test_search_by_admin_reviewed(self):
        self.generate_files(['Not Admin Reviewed', 'Admin Reviewed'])
        r = self.search(admin_review=1)
        eq_(self.named_addons(r), ['Admin Reviewed'])

    def test_queue_counts(self):
        self.generate_files(['Not Admin Reviewed', 'Admin Reviewed'])
        r = self.search(text_query='admin', per_page=1)
        doc = pq(r.content)
        eq_(doc('.data-grid-top .num-results').text(),
            u'Results 1 \u2013 1 of 2')

    def test_search_by_addon_name(self):
        self.generate_files(['Not Admin Reviewed', 'Admin Reviewed',
                             'Justin Bieber Theme'])
        r = self.search(text_query='admin')
        eq_(sorted(self.named_addons(r)), ['Admin Reviewed',
                                           'Not Admin Reviewed'])

    def test_search_by_addon_in_locale(self):
        name = 'Not Admin Reviewed'
        d = self.generate_file(name)
        uni = 'フォクすけといっしょ'.decode('utf8')
        a = Addon.objects.get(pk=d['addon'].id)
        a.name = {'ja': uni}
        a.save()
        r = self.client.get('/ja/' + self.url, {'text_query': uni},
                            follow=True)
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), [name])

    def test_search_by_addon_author(self):
        name = 'Not Admin Reviewed'
        d = self.generate_file(name)
        u = UserProfile.objects.all()[0]
        email = u.email.swapcase()
        author = AddonUser.objects.create(user=u, addon=d['addon'])
        for role in [amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV]:
            author.role = role
            author.save()
            r = self.search(text_query=email)
            eq_(self.named_addons(r), [name])
        author.role = amo.AUTHOR_ROLE_VIEWER
        author.save()
        r = self.search(text_query=email)
        eq_(self.named_addons(r), [])

    def test_search_by_supported_email_in_locale(self):
        name = 'Not Admin Reviewed'
        d = self.generate_file(name)
        uni = 'フォクすけといっしょ@site.co.jp'.decode('utf8')
        a = Addon.objects.get(pk=d['addon'].id)
        a.support_email = {'ja': uni}
        a.save()
        r = self.client.get('/ja/' + self.url, {'text_query': uni},
                            follow=True)
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), [name])

    def test_search_by_addon_type(self):
        self.generate_files(['Not Admin Reviewed', 'Justin Bieber Theme',
                             'Justin Bieber Search Bar'])
        r = self.search(addon_type_ids=[amo.ADDON_THEME])
        eq_(self.named_addons(r), ['Justin Bieber Theme'])

    def test_search_by_addon_type_any(self):
        self.generate_file('Not Admin Reviewed')
        r = self.search(addon_type_ids=[amo.ADDON_ANY])
        assert self.named_addons(r), 'Expected some add-ons'

    def test_search_by_many_addon_types(self):
        self.generate_files(['Not Admin Reviewed', 'Justin Bieber Theme',
                             'Justin Bieber Search Bar'])
        r = self.search(addon_type_ids=[amo.ADDON_THEME,
                                        amo.ADDON_SEARCH])
        eq_(sorted(self.named_addons(r)),
            ['Justin Bieber Search Bar', 'Justin Bieber Theme'])

    def test_search_by_platform_mac(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget',
                             'Mac Widget'])
        r = self.search(platform_ids=[amo.PLATFORM_MAC.id])
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), ['Mac Widget'])

    def test_search_by_platform_linux(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget',
                             'Mac Widget'])
        r = self.search(platform_ids=[amo.PLATFORM_LINUX.id])
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), ['Linux Widget'])

    def test_search_by_platform_mac_linux(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget',
                             'Mac Widget'])
        r = self.search(platform_ids=[amo.PLATFORM_MAC.id,
                                      amo.PLATFORM_LINUX.id])
        eq_(r.status_code, 200)
        eq_(sorted(self.named_addons(r)), ['Linux Widget', 'Mac Widget'])

    def test_preserve_multi_platform_files(self):
        for plat in (amo.PLATFORM_WIN, amo.PLATFORM_MAC):
            create_addon_file('Multi Platform', '0.1',
                              amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                              platform=plat)
        r = self.search(platform_ids=[amo.PLATFORM_WIN.id])
        eq_(r.status_code, 200)
        # Should not say Windows only.
        td = pq(r.content)('#addon-queue tbody td').eq(5)
        eq_(td.find('div').attr('title'), 'Firefox')
        eq_(td.text(), '')

    def test_preserve_single_platform_files(self):
        create_addon_file('Windows', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          platform=amo.PLATFORM_WIN)
        r = self.search(platform_ids=[amo.PLATFORM_WIN.id])
        doc = pq(r.content)
        eq_(doc('#addon-queue tbody td').eq(6).find('div').attr('title'),
            'Windows')

    def test_search_by_app(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget'])
        r = self.search(application_id=[amo.MOBILE.id])
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), ['Bieber For Mobile'])

    def test_preserve_multi_apps(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget'])
        for app in (amo.MOBILE, amo.FIREFOX):
            create_addon_file('Multi Application', '0.1',
                              amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                              application=app)

        r = self.search(application_id=[amo.MOBILE.id])
        doc = pq(r.content)
        td = doc('#addon-queue tr').eq(2).children('td').eq(5)
        eq_(td.children().length, 2)
        eq_(td.children('.ed-sprite-firefox').length, 1)
        eq_(td.children('.ed-sprite-mobile').length, 1)

    def test_search_by_version_requires_app(self):
        r = self.client.get(self.url, {'max_version': '3.6'})
        eq_(r.status_code, 200)
        # This is not the most descriptive message but it's
        # the easiest to show.  This missing app scenario is unlikely.
        eq_(r.context['search_form'].errors.as_text(),
            '* max_version\n  * Select a valid choice. 3.6 is not '
            'one of the available choices.')

    def test_search_by_app_version(self):
        d = create_addon_file('Bieber For Mobile 4.0b2pre', '0.1',
                              amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                              application=amo.MOBILE)
        app = Application.objects.get(pk=amo.MOBILE.id)
        max = AppVersion.objects.get(application=app, version='4.0b2pre')
        (ApplicationsVersions.objects
         .filter(application=app, version=d['version']).update(max=max))
        r = self.search(application_id=amo.MOBILE.id, max_version='4.0b2pre')
        eq_(self.named_addons(r), [u'Bieber For Mobile 4.0b2pre'])

    def test_age_of_submission(self):
        self.generate_files(['Not Admin Reviewed', 'Admin Reviewed',
                             'Justin Bieber Theme'])

        Version.objects.update(nomination=datetime.now() - timedelta(days=1))
        title = 'Justin Bieber Theme'
        bieber = Version.objects.filter(addon__name__localized_string=title)

        # Exclude anything out of range:
        bieber.update(nomination=datetime.now() - timedelta(days=5))
        r = self.search(waiting_time_days=2)
        addons = self.named_addons(r)
        assert title not in addons, ('Unexpected results: %r' % addons)

        # Include anything submitted up to requested days:
        bieber.update(nomination=datetime.now() - timedelta(days=2))
        r = self.search(waiting_time_days=5)
        addons = self.named_addons(r)
        assert title in addons, ('Unexpected results: %r' % addons)

        # Special case: exclude anything under 10 days:
        bieber.update(nomination=datetime.now() - timedelta(days=8))
        r = self.search(waiting_time_days='10+')
        addons = self.named_addons(r)
        assert title not in addons, ('Unexpected results: %r' % addons)

        # Special case: include anything 10 days and over:
        bieber.update(nomination=datetime.now() - timedelta(days=12))
        r = self.search(waiting_time_days='10+')
        addons = self.named_addons(r)
        assert title in addons, ('Unexpected results: %r' % addons)

    def test_form(self):
        self.generate_file('Bieber For Mobile')
        r = self.search()
        doc = pq(r.content)
        eq_(doc('#id_application_id').attr('data-url'),
            reverse('editors.application_versions_json'))
        eq_(doc('#id_max_version option').text(),
            'Select an application first')
        r = self.search(application_id=amo.MOBILE.id)
        doc = pq(r.content)
        eq_(doc('#id_max_version option').text(), '4.0b2pre 2.0a1pre 1.0')

    def test_application_versions_json(self):
        self.generate_file('Bieber For Mobile')
        r = self.client.post(reverse('editors.application_versions_json'),
                             {'application_id': amo.MOBILE.id})
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['choices'],
            [['', ''],
             ['4.0b2pre', '4.0b2pre'],
             ['2.0a1pre', '2.0a1pre'],
             ['1.0', '1.0']])

    def test_clear_search_visible(self):
        r = self.search(text_query='admin', searching=True)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#clear-queue-search').text(), 'clear search')

    def test_clear_search_hidden(self):
        r = self.search(text_query='admin')
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#clear-queue-search').text(), None)


class TestQueueSearchVersionSpecific(SearchTest):

    def setUp(self):
        super(TestQueueSearchVersionSpecific, self).setUp()
        self.url = reverse('editors.queue_prelim')
        create_addon_file('Not Admin Reviewed', '0.1',
                          amo.STATUS_LITE, amo.STATUS_UNREVIEWED)
        create_addon_file('Justin Bieber Theme', '0.1',
                          amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                          addon_type=amo.ADDON_THEME)
        self.bieber = Version.objects.filter(
                addon__name__localized_string='Justin Bieber Theme')

    def update_beiber(self, days):
        new_created = datetime.now() - timedelta(days=days)
        self.bieber.update(created=new_created)
        self.bieber[0].files.update(created=new_created)

    def test_age_of_submission(self):
        Version.objects.update(created=datetime.now() - timedelta(days=1))
        # Exclude anything out of range:
        self.update_beiber(5)
        r = self.search(waiting_time_days=2)
        addons = self.named_addons(r)
        assert 'Justin Bieber Theme' not in addons, (
            'Unexpected results: %r' % addons)
        # Include anything submitted up to requested days:
        self.update_beiber(2)
        r = self.search(waiting_time_days=4)
        addons = self.named_addons(r)
        assert 'Justin Bieber Theme' in addons, (
            'Unexpected results: %r' % addons)
        # Special case: exclude anything under 10 days:
        self.update_beiber(8)
        r = self.search(waiting_time_days='10+')
        addons = self.named_addons(r)
        assert 'Justin Bieber Theme' not in addons, (
            'Unexpected results: %r' % addons)
        # Special case: include anything 10 days and over:
        self.update_beiber(12)
        r = self.search(waiting_time_days='10+')
        addons = self.named_addons(r)
        assert 'Justin Bieber Theme' in addons, (
            'Unexpected results: %r' % addons)


class ReviewBase(QueueTest):

    def setUp(self):
        self.login_as_editor()
        self.addons = {}

        self.addon = self.generate_file('Public')
        self.version = self.addon.current_version
        self.editor = UserProfile.objects.get(username='editor')
        self.editor.update(display_name='An editor')
        self.url = reverse('editors.review', args=[self.addon.slug])

        AddonUser.objects.create(addon=self.addon, user_id=999)

    def get_addon(self):
        return Addon.objects.get(pk=self.addon.pk)

    def get_dict(self, **kw):
        files = [self.version.files.all()[0].pk]
        d = {'operating_systems': 'win', 'applications': 'something',
             'comments': 'something', 'addon_files': files}
        d.update(kw)
        return d


class TestReview(ReviewBase):

    def test_reviewer_required(self):
        eq_(self.client.head(self.url).status_code, 200)

    def test_not_anonymous(self):
        self.client.logout()
        r = self.client.head(self.url)
        self.assertRedirects(r,
            '%s?to=%s' % (reverse('users.login'), self.url))

    @patch.object(settings, 'DEBUG', False)
    def test_not_author(self):
        AddonUser.objects.create(addon=self.addon, user=self.editor)
        eq_(self.client.head(self.url).status_code, 302)

    def test_not_flags(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        eq_(len(response.context['flags']), 0)

    def test_flags(self):
        Review.objects.create(addon=self.addon, flag=True, user=self.editor)
        Review.objects.create(addon=self.addon, flag=False, user=self.editor)
        response = self.client.get(self.url)
        eq_(len(response.context['flags']), 1)

    def test_info_comments_requested(self):
        response = self.client.post(self.url, {'action': 'info'})
        eq_(response.context['form'].errors['comments'][0],
            'This field is required.')

    def test_comment(self):
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        eq_(response.status_code, 302)
        eq_(len(mail.outbox), 0)

        comment_version = amo.LOG.COMMENT_VERSION
        eq_(ActivityLog.objects.filter(action=comment_version.id).count(), 1)

    def test_info_requested(self):
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor'})
        eq_(response.status_code, 302)
        eq_(len(mail.outbox), 1)
        self.assertTemplateUsed(response, 'editors/emails/info.ltxt')

    def test_super_review_requested(self):
        response = self.client.post(self.url, {'action': 'super',
                                               'comments': 'hello sailor'})
        eq_(response.status_code, 302)
        eq_(len(mail.outbox), 2)
        self.assertTemplateUsed(response,
                                'editors/emails/author_super_review.ltxt')
        self.assertTemplateUsed(response, 'editors/emails/super_review.ltxt')

    def test_info_requested_canned_response(self):
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor',
                                               'canned_response': 'foo'})
        eq_(response.status_code, 302)
        eq_(len(mail.outbox), 1)
        self.assertTemplateUsed(response, 'editors/emails/info.ltxt')

    def test_notify(self):
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor',
                                               'notify': True})
        eq_(response.status_code, 302)
        eq_(EditorSubscription.objects.count(), 1)

    def test_no_notify(self):
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor'})
        eq_(response.status_code, 302)
        eq_(EditorSubscription.objects.count(), 0)

    def test_page_title(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        doc = pq(response.content)
        eq_(doc('title').text(),
            '%s :: Editor Tools :: Add-ons for Firefox' % self.addon.name)

    def test_breadcrumbs(self):
        self.generate_files()
        expected = [
            ('Pending Updates', reverse('editors.queue_pending')),
            (unicode(self.addon.name), None),
        ]
        self._test_breadcrumbs(expected)

    def test_paging_none(self):
        eq_(self.client.get(self.url).context['paging'], {})

    def test_paging_num(self):
        # 'Pending One' and 'Pending Two' should be the only ones present.
        self.generate_files()

        paging = self.client.get(self.url, dict(num=1)).context['paging']
        eq_(paging['prev'], False)
        eq_(paging['next'], True)
        eq_(paging['total'], 2)

        paging = self.client.get(self.url, dict(num=2)).context['paging']
        eq_(paging['prev'], True)
        eq_(paging['next'], False)

    def test_paging_error(self):
        response = self.client.get(self.url, dict(num='x'))
        eq_(response.status_code, 404)

    def test_files_shown(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        items = pq(r.content)('#review-files .files .file-info')
        eq_(items.length, 1)

        f = self.version.all_files[0]
        expected = [
            ('All Platforms', f.get_url_path('editor')),
            ('Validation',
             reverse('devhub.file_validation', args=[self.addon.slug, f.id])),
            ('Contents', None),
        ]
        check_links(expected, items.find('a'), verify=False)

    def test_item_history(self):
        self.addon_file(u'something', u'0.2', amo.STATUS_PUBLIC,
                        amo.STATUS_UNREVIEWED)
        eq_(self.addon.versions.count(), 1)
        self.review_version(self.version, self.url)

        v2 = self.addons['something'].versions.all()[0]
        v2.addon = self.addon
        v2.created = v2.created + timedelta(days=1)
        v2.save()
        self.review_version(v2, self.url)
        eq_(self.addon.versions.count(), 2)

        r = self.client.get(self.url)
        table = pq(r.content)('#review-files')

        # Check the history for both versions.
        ths = table.children('tr > th')
        eq_(ths.length, 2)
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()

        rows = table('td.files')
        eq_(rows.length, 2)

        comments = rows.siblings('td')
        eq_(comments.length, 2)

        for idx in xrange(comments.length):
            td = comments.eq(idx)
            eq_(td.find('.history-comment').text(), 'something')
            eq_(td.find('th').text(), 'Preliminarily approved')
            eq_(td.find('td a').text(), self.editor.display_name)

    def test_item_history_compat_ordered(self):
        """ Make sure that apps in compatibility are ordered. """
        self.addon_file(u'something', u'0.2', amo.STATUS_PUBLIC,
                        amo.STATUS_UNREVIEWED)

        a1, c = Application.objects.get_or_create(id=amo.THUNDERBIRD.id)
        a2, c = Application.objects.get_or_create(id=amo.SEAMONKEY.id)
        av = AppVersion.objects.all()[0]
        v = self.addon.versions.all()[0]

        ApplicationsVersions.objects.create(version=v,
                application=a1, min=av, max=av)

        ApplicationsVersions.objects.create(version=v,
                application=a2, min=av, max=av)

        eq_(self.addon.versions.count(), 1)
        url = reverse('editors.review', args=[self.addon.slug])

        doc = pq(self.client.get(url).content)
        icons = doc('.listing-body .app-icon')
        eq_(icons.eq(0).attr('title'), "Firefox")
        eq_(icons.eq(1).attr('title'), "SeaMonkey")
        eq_(icons.eq(2).attr('title'), "Thunderbird")

    def test_item_history_notes(self):
        v = self.addon.versions.all()[0]
        v.releasenotes = 'hi'
        v.approvalnotes = 'secret hi'
        v.save()

        r = self.client.get(self.url)
        doc = pq(r.content)('#review-files')

        version = doc('.activity_version')
        eq_(version.length, 1)
        eq_(version.text(), 'hi')

        approval = doc('.activity_approval')
        eq_(approval.length, 1)
        eq_(approval.text(), 'secret hi')

    def test_item_history_header(self):
        doc = pq(self.client.get(self.url).content)
        assert 'Listed' in doc('#review-files .listing-header .light').text()

    def test_item_history_comment(self):
        # Add Comment.
        self.addon_file(u'something', u'0.1', amo.STATUS_PUBLIC,
                        amo.STATUS_UNREVIEWED)
        self.client.post(self.url, {'action': 'comment',
                                    'comments': 'hello sailor'})

        r = self.client.get(self.url)
        doc = pq(r.content)('#review-files')
        eq_(doc('th').eq(1).text(), 'Comment')
        eq_(doc('.history-comment').text(), 'hello sailor')

    def test_files_in_item_history(self):
        data = {'action': 'public', 'operating_systems': 'win',
                'applications': 'something', 'comments': 'something',
                'addon_files': [self.version.files.all()[0].pk]}
        self.client.post(self.url, data)

        r = self.client.get(self.url)
        items = pq(r.content)('#review-files .files .file-info')
        eq_(items.length, 1)
        eq_(items.find('a.editors-install').text(), 'All Platforms')

    def test_no_items(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#review-files .no-activity').length, 1)

    def test_hide_beta(self):
        version = self.addon.latest_version
        f = version.files.all()[0]
        version.pk = None
        version.version = '0.3beta'
        version.save()

        doc = pq(self.client.get(self.url).content)
        eq_(doc('#review-files tr.listing-header').length, 2)

        f.pk = None
        f.status = amo.STATUS_BETA
        f.version = version
        f.save()

        doc = pq(self.client.get(self.url).content)
        eq_(doc('#review-files tr.listing-header').length, 1)

    def test_action_links(self):
        r = self.client.get(self.url)
        expected = [
            ('View Listing', self.addon.get_url_path()),
        ]
        check_links(expected, pq(r.content)('#actions-addon a'), verify=False)

    def test_action_links_as_admin(self):
        self.login_as_admin()
        r = self.client.get(self.url)
        expected = [
            ('View Listing', self.addon.get_url_path()),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page',
             reverse('zadmin.addon_manage', args=[self.addon.id])),
        ]
        check_links(expected, pq(r.content)('#actions-addon a'), verify=False)

    def test_admin_links_as_non_admin(self):
        self.login_as_editor()
        response = self.client.get(self.url)

        doc = pq(response.content)
        admin = doc('#actions-addon li')
        eq_(admin.length, 1)

    def test_unflag_option_forflagged_as_admin(self):
        self.login_as_admin()
        self.addon.update(admin_review=True)
        response = self.client.get(self.url)

        doc = pq(response.content)
        eq_(doc('#id_adminflag').length, 1)

    def test_unflag_option_forflagged_as_editor(self):
        self.login_as_editor()
        self.addon.update(admin_review=True)
        response = self.client.get(self.url)

        doc = pq(response.content)
        eq_(doc('#id_adminflag').length, 0)

    def test_unflag_option_notflagged_as_admin(self):
        self.login_as_admin()
        self.addon.update(admin_review=False)
        response = self.client.get(self.url)

        doc = pq(response.content)
        eq_(doc('#id_adminflag').length, 0)

    def test_unadmin_flag_as_admin(self):
        self.addon.update(admin_review=True)
        self.login_as_admin()
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor',
                                               'adminflag': True})
        eq_(response.status_code, 302,
            "Review should be processed as normal and redirect")
        self.assertRedirects(response, reverse('editors.queue_pending'),
                             status_code=302)
        eq_(Addon.objects.get(pk=self.addon.pk).admin_review, False,
            "Admin flag should still be removed if admin")

    def test_unadmin_flag_as_editor(self):
        self.addon.update(admin_review=True)
        self.login_as_editor()
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor',
                                               'adminflag': True})
        eq_(response.status_code, 302,
            "Review should be processed as normal and redirect")
        # Should silently fail to set adminflag but work otherwise.
        self.assertRedirects(response, reverse('editors.queue_pending'),
                             status_code=302)
        eq_(Addon.objects.get(pk=self.addon.pk).admin_review, True,
            "Admin flag should still be in place if editor")

    def test_no_public(self):
        s = amo.STATUS_PUBLIC

        has_public = self.version.files.filter(status=s).exists()
        assert not has_public

        for version_file in self.version.files.all():
            version_file.status = amo.STATUS_PUBLIC
            version_file.save()

        has_public = self.version.files.filter(status=s).exists()
        assert has_public

        response = self.client.get(self.url)

        validation = pq(response.content).find('.files')
        eq_(validation.find('a').eq(1).text(), "Validation")
        eq_(validation.find('a').eq(2).text(), "Contents")

        eq_(validation.find('a').length, 3)

    def test_public_search(self):
        self.version.files.update(status=amo.STATUS_PUBLIC)
        self.addon.update(type=amo.ADDON_SEARCH)
        r = self.client.get(self.url)
        eq_(pq(r.content)('#review-files .files ul .file-info').length, 1)

    def test_version_deletion(self):
        """
        Make sure that we still show review history for deleted versions.
        """
        # Add a new version to the add-on.
        self.addon_file(u'something', u'0.2', amo.STATUS_PUBLIC,
                        amo.STATUS_UNREVIEWED)

        eq_(self.addon.versions.count(), 1)

        self.review_version(self.version, self.url)

        v2 = self.addons['something'].versions.all()[0]
        v2.addon = self.addon
        v2.created = v2.created + timedelta(days=1)
        v2.save()
        self.review_version(v2, self.url)
        eq_(self.addon.versions.count(), 2)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # View the history verify two versions:
        ths = doc('table#review-files > tr > th:first-child')
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()

        # Delete a version:
        v2.delete()
        # Verify two versions, one deleted:
        r = self.client.get(self.url)
        doc = pq(r.content)
        ths = doc('table#review-files > tr > th:first-child')

        eq_(ths.length, 1)
        assert '0.1' in ths.text()

    def review_version(self, version, url):
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)
        d = dict(action='prelim', operating_systems='win',
                 applications='something', comments='something',
                 addon_files=[version.files.all()[0].pk])
        self.client.post(url, d)

    def test_dependencies_listed(self):
        AddonDependency.objects.create(addon=self.addon,
                                       dependent_addon=self.addon)
        r = self.client.get(self.url)
        deps = pq(r.content)('#addon-summary .addon-dependencies')
        eq_(deps.length, 1)
        eq_(deps.find('li').length, 1)
        eq_(deps.find('a').attr('href'), self.addon.get_url_path())

    def test_eula_displayed(self):
        eq_(bool(self.addon.has_eula), False)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertNotContains(r, 'View EULA')

        self.addon.eula = 'Test!'
        self.addon.save()
        eq_(bool(self.addon.has_eula), True)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertContains(r, 'View EULA')

    def test_privacy_policy_displayed(self):
        eq_(self.addon.privacy_policy, None)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertNotContains(r, 'View Privacy Policy')

        self.addon.privacy_policy = 'Test!'
        self.addon.save()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertContains(r, 'View Privacy Policy')

    def test_breadcrumbs_all(self):
        queues = {'Full Reviews': [amo.STATUS_NOMINATED,
                                   amo.STATUS_LITE_AND_NOMINATED],
                  'Preliminary Reviews': [amo.STATUS_UNREVIEWED,
                                          amo.STATUS_LITE],
                  'Pending Updates': [amo.STATUS_PENDING, amo.STATUS_PUBLIC]}
        for text, queue_ids in queues.items():
            for qid in queue_ids:
                self.addon.update(status=qid)
                doc = pq(self.client.get(self.url).content)
                eq_(doc('#breadcrumbs li:eq(1)').text(), text)

    def test_viewing(self):
        url = reverse('editors.review_viewing')
        r = self.client.post(url, {'addon_id': self.addon.id})
        data = json.loads(r.content)
        eq_(data['current'], self.editor.id)
        eq_(data['current_name'], self.editor.name)
        eq_(data['is_user'], 1)

        # Now, login as someone else and test.
        self.login_as_admin()
        r = self.client.post(url, {'addon_id': self.addon.id})
        data = json.loads(r.content)
        eq_(data['current'], self.editor.id)
        eq_(data['current_name'], self.editor.name)
        eq_(data['is_user'], 0)

    def test_viewing_queue(self):
        r = self.client.post(reverse('editors.review_viewing'),
                             {'addon_id': self.addon.id})
        data = json.loads(r.content)
        eq_(data['current'], self.editor.id)
        eq_(data['current_name'], self.editor.name)
        eq_(data['is_user'], 1)

        # Now, login as someone else and test.
        self.login_as_admin()
        r = self.client.post(reverse('editors.queue_viewing'),
                             {'addon_ids': self.addon.id})
        data = json.loads(r.content)
        eq_(data[str(self.addon.id)], self.editor.display_name)

    def test_no_compare_link(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        info = pq(r.content)('#review-files .file-info')
        eq_(info.length, 1)
        eq_(info.find('a.compare').length, 0)

    def test_compare_link(self):
        version = Version.objects.create(addon=self.addon, version='0.2')
        version.created = datetime.today() + timedelta(days=1)
        version.save()

        f1 = self.addon.versions.order_by('created')[0].files.all()[0]
        f1.status = amo.STATUS_PUBLIC
        f1.save()

        f2 = File.objects.create(version=version, status=amo.STATUS_PUBLIC)
        self.addon.update(_current_version=version)
        eq_(self.addon.current_version, version)

        r = self.client.get(self.url)
        assert r.context['show_diff']
        links = pq(r.content)('#review-files .file-info .compare')
        expected = [
            reverse('files.compare', args=[f1.pk, f1.pk]),
            reverse('files.compare', args=[f2.pk, f1.pk]),
        ]
        check_links(expected, links, verify=False)


class TestReviewPreliminary(ReviewBase):

    def prelim_dict(self):
        return self.get_dict(action='prelim')

    def test_prelim_comments_requested(self):
        response = self.client.post(self.url, {'action': 'prelim'})
        eq_(response.context['form'].errors['comments'][0],
            'This field is required.')

    def test_prelim_from_lite(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)
        response = self.client.post(self.url, self.prelim_dict())
        eq_(response.status_code, 302)
        eq_(self.get_addon().status, amo.STATUS_LITE)

    def test_prelim_from_lite_required(self):
        self.addon.update(status=amo.STATUS_LITE)
        response = self.client.post(self.url, {'action': 'prelim'})
        eq_(response.context['form'].errors['comments'][0],
            'This field is required.')

    def test_prelim_from_lite_no_files(self):
        self.addon.update(status=amo.STATUS_LITE)
        data = self.prelim_dict()
        del data['addon_files']
        response = self.client.post(self.url, data)
        eq_(response.context['form'].errors['addon_files'][0],
            'You must select some files.')

    def test_prelim_from_lite_wrong(self):
        self.addon.update(status=amo.STATUS_LITE)
        response = self.client.post(self.url, self.prelim_dict())
        eq_(response.context['form'].errors['addon_files'][0],
            'File Public.xpi is not pending review.')

    def test_prelim_from_lite_wrong_two(self):
        self.addon.update(status=amo.STATUS_LITE)
        data = self.prelim_dict()
        f = self.version.files.all()[0]

        statuses = dict(amo.STATUS_CHOICES)  # Deep copy.
        del statuses[amo.STATUS_BETA], statuses[amo.STATUS_UNREVIEWED]
        for status in statuses:
            f.update(status=status)
            response = self.client.post(self.url, data)
            eq_(response.context['form'].errors['addon_files'][0],
                'File Public.xpi is not pending review.')

    def test_prelim_from_lite_files(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.client.post(self.url, self.prelim_dict())
        eq_(self.get_addon().status, amo.STATUS_LITE)

    def test_prelim_from_unreviewed(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        response = self.client.post(self.url, self.prelim_dict())
        eq_(response.status_code, 302)
        eq_(self.get_addon().status, amo.STATUS_LITE)

    def test_prelim_multiple_files(self):
        f = self.version.files.all()[0]
        f.pk = None
        f.status = amo.STATUS_DISABLED
        f.save()
        self.addon.update(status=amo.STATUS_LITE)
        data = self.prelim_dict()
        data['addon_files'] = [f.pk]
        self.client.post(self.url, data)
        eq_([amo.STATUS_DISABLED, amo.STATUS_LISTED],
            [f.status for f in self.version.files.all().order_by('status')])


class TestReviewPending(ReviewBase):

    def setUp(self):
        super(TestReviewPending, self).setUp()
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.file = File.objects.create(version=self.version,
                                        status=amo.STATUS_UNREVIEWED)

    def pending_dict(self):
        files = list(self.version.files.values_list('id', flat=True))
        return self.get_dict(action='public', addon_files=files)

    def test_pending_to_public(self):
        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        eq_(list(statuses), [amo.STATUS_UNREVIEWED, amo.STATUS_LISTED])

        r = self.client.post(self.url, self.pending_dict())
        self.assertRedirects(r, reverse('editors.queue_pending'))
        eq_(self.get_addon().status, amo.STATUS_PUBLIC)

        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        eq_(list(statuses), [amo.STATUS_PUBLIC] * 2)

    def test_disabled_file(self):
        obj = File.objects.create(version=self.version,
                                  status=amo.STATUS_DISABLED)
        response = self.client.get(self.url, self.pending_dict())
        doc = pq(response.content)
        assert 'disabled' in doc('#file-%s' % obj.pk)[0].keys()
        assert 'disabled' not in doc('#file-%s' % self.file.pk)[0].keys()


class TestEditorMOTD(EditorTest):

    def get_url(self, save=False):
        return reverse('editors.%smotd' % ('save_' if save else ''))

    def test_change_motd(self):
        self.login_as_admin()
        motd = "Let's get crazy"
        r = self.client.post(self.get_url(save=True), {'motd': motd})
        url = self.get_url()
        self.assertRedirects(r, url)
        r = self.client.get(url)
        eq_(pq(r.content)('.daily-message p').text(), motd)

    def test_require_editor_to_view(self):
        url = self.get_url()
        r = self.client.head(url)
        self.assertRedirects(r, '%s?to=%s' % (reverse('users.login'), url))

    def test_require_admin_to_change_motd(self):
        self.login_as_editor()
        r = self.client.post(reverse('editors.save_motd'),
                             {'motd': "I'm a sneaky editor"})
        eq_(r.status_code, 403)

    def test_editor_can_view_not_edit(self):
        motd = 'Some announcement'
        set_config('editors_review_motd', motd)
        self.login_as_editor()
        r = self.client.get(self.get_url())
        eq_(pq(r.content)('.daily-message p').text(), motd)
        eq_(r.context['form'], None)

    def test_motd_edit_group(self):
        user = UserProfile.objects.get(email='editor@mozilla.com')
        group = Group.objects.create(name='Add-on Reviewer MOTD',
                                     rules='AddonReviewerMOTD:Edit')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_editor()
        r = self.client.post(reverse('editors.save_motd'),
                             {'motd': 'I am the keymaster.'})
        eq_(r.status_code, 302)
        eq_(get_config('editors_review_motd'), 'I am the keymaster.')

    def test_form_errors(self):
        self.login_as_admin()
        r = self.client.post(self.get_url(save=True))
        doc = pq(r.content)
        eq_(doc('#editor-motd .errorlist').text(), 'This field is required.')


class TestStatusFile(ReviewBase):

    def get_file(self):
        return self.version.files.all()[0]

    def check_status(self, expected):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#review-files .file-info div').text(), expected)

    def test_status_prelim(self):
        for status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE]:
            self.addon.update(status=status)
            self.check_status('Pending Preliminary Review')

    def test_status_full(self):
        for status in [amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                       amo.STATUS_PUBLIC]:
            self.addon.update(status=status)
            self.check_status('Pending Full Review')

    def test_status_full_reviewed(self):
        self.get_file().update(status=amo.STATUS_PUBLIC)
        for status in set(amo.STATUS_UNDER_REVIEW + amo.LITE_STATUSES):
            self.addon.update(status=status)
            self.check_status('Fully Reviewed')

    def test_other(self):
        self.addon.update(status=amo.STATUS_BETA)
        self.check_status(unicode(amo.STATUS_CHOICES[self.get_file().status]))


class TestAbuseReports(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        user = UserProfile.objects.all()[0]
        AbuseReport.objects.create(addon_id=3615, message='woo')
        AbuseReport.objects.create(addon_id=3615, message='yeah',
                                   reporter=user)
        # Make a user abuse report to make sure it doesn't show up.
        AbuseReport.objects.create(user=user, message='hey now')

    def test_abuse_reports_list(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('editors.abuse_reports', args=['a3615']))
        eq_(r.status_code, 200)
        # We see the two abuse reports created in setUp.
        eq_(len(r.context['reports']), 2)
