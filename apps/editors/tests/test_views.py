# -*- coding: utf8 -*-
import re
import time
from datetime import datetime

from django import forms

from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse
from amo.tests import formset, initial
from addons.models import Addon
from devhub.models import ActivityLog
from editors.models import EventLog
import reviews
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from versions.models import Version
from files.models import Approval, Platform, File
from . test_models import create_addon_file


class EditorTest(test_utils.TestCase):
    fixtures = ('base/users', 'editors/pending-queue', 'base/approvals')

    def login_as_editor(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def make_review(self, username='a'):
        u = UserProfile.objects.create(username=username)
        a = Addon.objects.create(name='yermom', type=amo.ADDON_EXTENSION)
        return Review.objects.create(user=u, addon=a)


class TestEventLog(EditorTest):
    def setUp(self):
        self.login_as_editor()
        amo.set_user(UserProfile.objects.get(username='editor'))
        review = self.make_review()
        for i in xrange(30):
            amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon)
            amo.log(amo.LOG.DELETE_REVIEW, review.id, review.addon)

    def test_log(self):
        r = self.client.get(reverse('editors.eventlog'))
        eq_(r.status_code, 200)

    def test_start_filter(self):
        r = self.client.get(reverse('editors.eventlog') + '?start=3011-01-01')
        eq_(r.status_code, 200)
        doc = pq(r.content)
        assert doc('tbody')
        eq_(len(doc('tbody tr')), 0)

    def test_enddate_filter(self):
        """
        Make sure that if our end date is 1/1/2011, that we include items from
        1/1/2011.  To not do as such would be dishonorable.
        """
        review = self.make_review(username='b')
        amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon,
                created=datetime(2011, 1, 1))

        r = self.client.get(reverse('editors.eventlog') + '?end=2011-01-01')
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('tbody td').eq(0).text(), 'Jan 1, 2011 12:00:00 AM')

    def test_action_filter(self):
        """
        Based on setup we should only see 30 items if we filter for deleted
        reviews.
        """
        r = self.client.get(reverse('editors.eventlog') + '?filter=deleted')
        doc = pq(r.content)
        eq_(len(doc('tbody tr')), 30)


class TestEventLogDetail(TestEventLog):
    def test_me(self):
        id = ActivityLog.objects.editor_events()[0].id
        r = self.client.get(reverse('editors.eventlog.detail', args=[id]))
        eq_(r.status_code, 200)


class TestReviewLog(EditorTest):
    def setUp(self):
        self.login_as_editor()
        self.make_approvals()

    def make_approvals(self):
        Platform.objects.create(id=amo.PLATFORM_ALL.id)
        u = UserProfile.objects.filter()[0]
        for i in xrange(51):
            a = Addon.objects.create(type=amo.ADDON_EXTENSION)
            v = Version.objects.create(addon=a)
            amo.log(amo.LOG.REJECT_VERSION, a, v, user=u,
                    details={'comments': 'youwin'})

    def test_basic(self):
        r = self.client.get(reverse('editors.reviewlog'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        assert doc('.listing button'), 'No filters.'
        # Should have 50 showing.
        eq_(len(doc('tbody tr').not_('.hide')), 50)
        eq_(doc('tbody tr.hide').eq(0).text(), 'youwin')

    def test_end_filter(self):
        """
        Let's use today as an end-day filter and make sure we see stuff if we
        filter.
        """
        # Make sure we show the stuff we just made.
        date = time.strftime('%Y-%m-%d')
        r = self.client.get(reverse('editors.reviewlog') + '?end=' + date)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(len(doc('tbody tr').not_('.hide')), 50)
        eq_(doc('tbody tr.hide').eq(0).text(), 'youwin')


class TestHome(EditorTest):
    """Test the page at /editors."""
    def setUp(self):
        self.login_as_editor()
        self.user = UserProfile.objects.get(id=5497308)
        self.user.display_name = 'editor'
        self.user.save()
        amo.set_user(self.user)

    def approve_reviews(self):
        Platform.objects.create(id=amo.PLATFORM_ALL.id)
        u = self.user

        now = datetime.now()
        created = datetime(now.year - 1, now.month, 1)

        for i in xrange(50):
            a = Addon.objects.create(type=amo.ADDON_EXTENSION)
            v = Version.objects.create(addon=a)
            f = File.objects.create(version=v)

            Approval(addon=a, user=u, file=f, created=created).save()

    def test_approved_review(self):
        review = self.make_review()
        amo.log(amo.LOG.APPROVE_REVIEW, review, review.addon)
        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)
        eq_(doc('.row').eq(0).text().strip().split('.')[0],
            'editor approved Review for yermom ')

    def test_deleted_review(self):
        review = self.make_review()
        amo.log(amo.LOG.DELETE_REVIEW, review.id, review.addon)
        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)
        eq_(doc('.row').eq(0).text().strip().split('.')[0],
            'editor deleted review %d' % review.id)

    def test_stats_total(self):
        review = self.approve_reviews()

        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)

        display_name = doc('.editor-stats-table:eq(0)').find('td')[0].text
        eq_(display_name, self.user.display_name)

        approval_count = doc('.editor-stats-table:eq(0)').find('td')[1].text
        # 50 generated + 1 fixture from a past month
        eq_(int(approval_count), 51)

    def test_stats_monthly(self):
        review = self.approve_reviews()

        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)

        display_name = doc('.editor-stats-table:eq(1)').find('td')[0].text
        eq_(display_name, self.user.display_name)

        approval_count = doc('.editor-stats-table:eq(1)').find('td')[1].text
        # 50 generated; doesn't show the fixture from a past month
        eq_(int(approval_count), 50)

    def test_new_editors(self):
        EventLog(type='admin', action='group_addmember', changed_id=2,
                 added=self.user.id, user=self.user).save()

        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)

        name =  doc('.editor-stats-table:eq(2)').find('td a')[0].text.strip()
        eq_(name, self.user.display_name)

class QueueTest(EditorTest):
    fixtures = ['base/users']

    def setUp(self):
        super(QueueTest, self).setUp()
        self.login_as_editor()
        self.versions = {}
        self.addon_file(u'Pending One', u'0.1',
                        amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED)
        self.addon_file(u'Pending Two', u'0.1',
                        amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED)
        self.addon_file(u'Nominated One', u'0.1',
                        amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        self.addon_file(u'Nominated Two', u'0.1',
                        amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_UNREVIEWED)
        self.addon_file(u'Prelim One', u'0.1',
                        amo.STATUS_LITE, amo.STATUS_UNREVIEWED)
        self.addon_file(u'Prelim Two', u'0.1',
                        amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED)
        self.addon_file(u'Public', u'0.1',
                        amo.STATUS_PUBLIC, amo.STATUS_LISTED)

    def addon_file(self, *args, **kw):
        a = create_addon_file(*args, **kw)
        self.versions[unicode(a['addon'].name)] = a['version']


class TestQueueBasics(QueueTest):

    def test_only_viewable_by_editor(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 403)

    def test_invalid_page(self):
        r = self.client.get(reverse('editors.queue_pending'),
                            data={'page': 999})
        eq_(r.status_code, 200)
        eq_(r.context['page'].number, 1)

    def test_redirect_to_review(self):
        r = self.client.get(reverse('editors.queue_pending'), data={'num': 2})
        self.assertRedirects(r, reverse('editors.review',
                        args=[self.versions['Pending Two'].id]) + '?num=2')

    def test_invalid_review_ignored(self):
        r = self.client.get(reverse('editors.queue_pending'), data={'num': 9})
        eq_(r.status_code, 200)

    def test_garbage_review_num_ignored(self):
        r = self.client.get(reverse('editors.queue_pending'),
                            data={'num': 'not-a-number'})
        eq_(r.status_code, 200)

    def test_grid_headers(self):
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('div.section table tr th:eq(0)').text(), u'Addon')
        eq_(doc('div.section table tr th:eq(1)').text(), u'Type')
        eq_(doc('div.section table tr th:eq(2)').text(), u'Waiting Time')
        eq_(doc('div.section table tr th:eq(3)').text(), u'Flags')
        eq_(doc('div.section table tr th:eq(4)').text(), u'Applications')
        eq_(doc('div.section table tr th:eq(5)').text(),
            u'Additional Information')


class TestPendingQueue(QueueTest):

    def test_results(self):
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        row = doc('div.section table tr:eq(1)')
        eq_(doc('td:eq(0)', row).text(), u'Pending One 0.1')
        eq_(doc('td a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Pending One'].id]) + '?num=1')
        row = doc('div.section table tr:eq(2)')
        eq_(doc('td:eq(0)', row).text(), u'Pending Two 0.1')
        eq_(doc('a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Pending Two'].id]) + '?num=2')

    def test_queue_count(self):
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(1)').text(), u'Pending Updates (2)')
        eq_(doc('.tabnav li a:eq(1)').attr('href'),
            reverse('editors.queue_pending'))


class TestNominatedQueue(QueueTest):

    def test_results(self):
        r = self.client.get(reverse('editors.queue_nominated'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        row = doc('div.section table tr:eq(1)')
        eq_(doc('td:eq(0)', row).text(), u'Nominated One 0.1')
        eq_(doc('td a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Nominated One'].id]) + '?num=1')
        row = doc('div.section table tr:eq(2)')
        eq_(doc('td:eq(0)', row).text(), u'Nominated Two 0.1')
        eq_(doc('a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Nominated Two'].id]) + '?num=2')

    def test_queue_count(self):
        r = self.client.get(reverse('editors.queue_nominated'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(0)').text(), u'Full Reviews (2)')
        eq_(doc('.tabnav li a:eq(0)').attr('href'),
            reverse('editors.queue_nominated'))


class TestPreliminaryQueue(QueueTest):

    def test_results(self):
        r = self.client.get(reverse('editors.queue_prelim'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        row = doc('div.section table tr:eq(1)')
        eq_(doc('td:eq(0)', row).text(), u'Prelim One 0.1')
        eq_(doc('td a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Prelim One'].id]) + '?num=1')
        row = doc('div.section table tr:eq(2)')
        eq_(doc('td:eq(0)', row).text(), u'Prelim Two 0.1')
        eq_(doc('a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Prelim Two'].id]) + '?num=2')

    def test_queue_count(self):
        r = self.client.get(reverse('editors.queue_prelim'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(2)').text(), u'Preliminary Reviews (2)')
        eq_(doc('.tabnav li a:eq(2)').attr('href'),
            reverse('editors.queue_prelim'))


class TestModeratedQueue(QueueTest):
    fixtures = ['base/users', 'base/apps', 'reviews/dev-reply.json']

    def setUp(self):
        self.url = reverse('editors.queue_moderated')
        url_flag = reverse('reviews.flag', args=['a1865', 218468])

        self.login_as_editor()
        response = self.client.post(url_flag, {'flag': ReviewFlag.SPAM})
        eq_(response.status_code, 200)

        eq_(ReviewFlag.objects.filter(flag=ReviewFlag.SPAM).count(), 1)
        eq_(Review.objects.filter(editorreview=True).count(), 1)

    def test_results(self):
        r = self.client.get(reverse('editors.queue_moderated'))
        eq_(r.status_code, 200)
        doc = pq(r.content)

        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        eq_(len(rows), 1)

        row = rows[0]

        assert re.findall("Don't use Firefox", doc('h3', row).text())

        # Default is "Skip"
        assert doc('#id_form-0-action_1:checked')

    def setup_actions(self, action):
        ctx = self.client.get(self.url).context
        fs = initial(ctx['reviews_formset'].forms[0])

        eq_(len(Review.objects.filter(addon=1865)), 2)

        data_formset = formset(fs)
        data_formset['form-0-action'] = action

        r = self.client.post(reverse('editors.queue_moderated'), data_formset)
        eq_(r.status_code, 302)

    def test_skip(self):
        self.setup_actions(reviews.REVIEW_MODERATE_SKIP)

        # Make sure it's still there.
        r = self.client.get(reverse('editors.queue_moderated'))
        doc = pq(r.content)
        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        eq_(len(rows), 1)

    def test_remove(self):
        """ Make sure the editor tools can delete a review. """
        al = ActivityLog.objects.filter(action=amo.LOG.DELETE_REVIEW.id)
        al_start = al.count()
        self.setup_actions(reviews.REVIEW_MODERATE_DELETE)

        # Make sure it's removed from the queue.
        r = self.client.get(reverse('editors.queue_moderated'))
        doc = pq(r.content)
        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        eq_(len(rows), 0)

        # Make sure it was actually deleted.
        eq_(len(Review.objects.filter(addon=1865)), 1)

        # One activity logged.
        al_end = ActivityLog.objects.filter(action=amo.LOG.DELETE_REVIEW.id)
        eq_(al_start + 1, al_end.count())

    def test_keep(self):
        """ Make sure the editor tools can remove flags and keep a review. """
        al = ActivityLog.objects.filter(action=amo.LOG.APPROVE_REVIEW.id)
        al_start = al.count()
        self.setup_actions(reviews.REVIEW_MODERATE_KEEP)

        # Make sure it's removed from the queue.
        r = self.client.get(reverse('editors.queue_moderated'))
        doc = pq(r.content)
        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        eq_(len(rows), 0)

        # Make sure it's NOT deleted.
        eq_(len(Review.objects.filter(addon=1865)), 2)

        # One activity logged.
        al_end = ActivityLog.objects.filter(action=amo.LOG.APPROVE_REVIEW.id)
        eq_(al_start + 1, al_end.count())

    def test_queue_count(self):
        r = self.client.get(reverse('editors.queue_moderated'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.tabnav li a:eq(3)').text(), u'Moderated Review (1)')
        eq_(doc('.tabnav li a:eq(3)').attr('href'),
            reverse('editors.queue_moderated'))
