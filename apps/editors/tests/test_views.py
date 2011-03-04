# -*- coding: utf8 -*-
import json
import re
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail

from mock import patch_object
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse
from amo.tests import formset, initial
from addons.models import Addon, AddonUser
from applications.models import Application
from devhub.models import ActivityLog
from editors.models import EventLog
import reviews
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from versions.models import Version, VersionSummary, AppVersion
from files.models import Approval, Platform, File
from zadmin.models import set_config, get_config
from . test_models import create_addon_file


class EditorTest(test_utils.TestCase):
    fixtures = ('base/users', 'editors/pending-queue', 'base/approvals')

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
        self.approve_reviews()

        r = self.client.get(reverse('editors.home'))
        doc = pq(r.content)

        display_name = doc('.editor-stats-table:eq(0)').find('td')[0].text
        eq_(display_name, self.user.display_name)

        approval_count = doc('.editor-stats-table:eq(0)').find('td')[1].text
        # 50 generated + 1 fixture from a past month
        eq_(int(approval_count), 51)

    def test_stats_monthly(self):
        self.approve_reviews()

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

        name = doc('.editor-stats-table:eq(2)').find('td a')[0].text.strip()
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

    def test_invalid_per_page(self):
        r = self.client.get(reverse('editors.queue_pending'),
                            data={'per_page': '<garbage>'})
        # No exceptions:
        eq_(r.status_code, 200)

    def test_redirect_to_review(self):
        r = self.client.get(reverse('editors.queue_pending'), data={'num': 2})
        self.assertRedirects(r,
                    reverse('editors.review',
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
        eq_(doc('table.data-grid tr th:eq(0)').text(), u'Addon')
        eq_(doc('table.data-grid tr th:eq(1)').text(), u'Type')
        eq_(doc('table.data-grid tr th:eq(2)').text(), u'Waiting Time')
        eq_(doc('table.data-grid tr th:eq(3)').text(), u'Flags')
        eq_(doc('table.data-grid tr th:eq(4)').text(), u'Applications')
        eq_(doc('table.data-grid tr th:eq(5)').text(),
            u'Additional Information')


class TestPendingQueue(QueueTest):

    def test_results(self):
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        row = doc('table.data-grid tr:eq(1)')
        eq_(doc('td:eq(0)', row).text(), u'Pending One 0.1')
        eq_(doc('td a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Pending One'].id]) + '?num=1')
        row = doc('table.data-grid tr:eq(2)')
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
        row = doc('table.data-grid tr:eq(1)')
        eq_(doc('td:eq(0)', row).text(), u'Nominated One 0.1')
        eq_(doc('td a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Nominated One'].id]) + '?num=1')
        row = doc('table.data-grid tr:eq(2)')
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
        row = doc('table.data-grid tr:eq(1)')
        eq_(doc('td:eq(0)', row).text(), u'Prelim One 0.1')
        eq_(doc('td a:eq(0)', row).attr('href'),
            reverse('editors.review',
                    args=[self.versions[u'Prelim One'].id]) + '?num=1')
        row = doc('table.data-grid tr:eq(2)')
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

        review = Review.objects.filter(addon=1865, editorreview=1)
        eq_(len(review), 1)

        self.setup_actions(reviews.REVIEW_MODERATE_KEEP)

        # Make sure it's removed from the queue.
        r = self.client.get(reverse('editors.queue_moderated'))
        doc = pq(r.content)
        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        eq_(len(rows), 0)

        review = Review.objects.filter(addon=1865)

        # Make sure it's NOT deleted...
        eq_(len(review), 2)

        # ...but it's no longer flagged
        eq_(len(review.filter(editorreview=1)), 0)

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


class SearchTest(EditorTest):

    def setUp(self):
        self.login_as_editor()

    def named_addons(self, request):
        return [row.data.addon_name
                for row in request.context['page'].object_list]

    def search(self, data):
        r = self.client.get(self.url, data=data)
        eq_(r.status_code, 200)
        eq_(r.context['search_form'].errors.as_text(), '')
        return r


class TestQueueSearch(SearchTest):
    fixtures = ('base/users', 'base/apps', 'base/appversion')

    def setUp(self):
        super(TestQueueSearch, self).setUp()
        self.url = reverse('editors.queue_nominated')
        create_addon_file('Not Admin Reviewed', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        create_addon_file('Admin Reviewed', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          admin_review=True)
        create_addon_file('Justin Bieber Persona', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          addon_type=amo.ADDON_THEME)
        create_addon_file('Justin Bieber Search Bar', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          addon_type=amo.ADDON_SEARCH)
        create_addon_file('Bieber For Mobile', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          application=amo.MOBILE)
        create_addon_file('Linux Widget', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          platform=amo.PLATFORM_LINUX)
        create_addon_file('Mac Widget', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          platform=amo.PLATFORM_MAC)

    def test_search_by_admin_reviewed(self):
        r = self.search({'admin_review': 1})
        eq_(self.named_addons(r), ['Admin Reviewed'])

    def test_queue_counts(self):
        r = self.search({'text_query': 'admin', 'per_page': 1})
        doc = pq(r.content)
        eq_(doc('.data-grid-top .num-results').text(),
            u'Results 1 \u2013 1 of 2')

    def test_search_by_addon_name(self):
        r = self.search({'text_query': 'admin'})
        eq_(sorted(self.named_addons(r)), ['Admin Reviewed',
                                           'Not Admin Reviewed'])

    def test_search_by_addon_in_locale(self):
        uni = 'フォクすけといっしょ'.decode('utf8')
        d = create_addon_file('Some Addon', '0.1',
                              amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        a = Addon.objects.get(pk=d['addon'].id)
        a.name = {'ja': uni}
        a.save()
        r = self.client.get('/ja/' + self.url, data={'text_query': uni},
                            follow=True)
        eq_(r.status_code, 200)
        eq_(sorted(self.named_addons(r)), ['Some Addon'])

    def test_search_by_addon_author(self):
        d = create_addon_file('For Author Search', '0.1',
                              amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        u = UserProfile.objects.create(username='fligtar',
                                       email='Fligtar@fligtar.com')
        au = AddonUser.objects.create(user=u, addon=d['addon'])
        author = AddonUser.objects.filter(id=au.id)
        for role in [amo.AUTHOR_ROLE_OWNER,
                     amo.AUTHOR_ROLE_DEV]:
            author.update(role=role)
            r = self.search({'text_query': 'fligtar@fligtar.com'})
            eq_(self.named_addons(r), ['For Author Search'])
        author.update(role=amo.AUTHOR_ROLE_VIEWER)
        r = self.search({'text_query': 'fligtar@fligtar.com'})
        eq_(self.named_addons(r), [])

    def test_search_by_supported_email_in_locale(self):
        d = create_addon_file('Some Addon', '0.1',
                              amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        uni = 'フォクすけといっしょ@site.co.jp'.decode('utf8')
        a = Addon.objects.get(pk=d['addon'].id)
        a.support_email = {'ja': uni}
        a.save()
        r = self.client.get('/ja/' + self.url, data={'text_query': uni},
                            follow=True)
        eq_(r.status_code, 200)
        eq_(sorted(self.named_addons(r)), ['Some Addon'])

    def test_search_by_addon_type(self):
        r = self.search({'addon_type_ids': [amo.ADDON_THEME]})
        eq_(self.named_addons(r), ['Justin Bieber Persona'])

    def test_search_by_many_addon_types(self):
        r = self.search({'addon_type_ids': [amo.ADDON_THEME,
                                            amo.ADDON_SEARCH]})
        eq_(sorted(self.named_addons(r)),
            ['Justin Bieber Persona', 'Justin Bieber Search Bar'])

    def test_search_by_platform_mac(self):
        r = self.search({'platform_ids': [amo.PLATFORM_MAC.id]})
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), ['Mac Widget'])

    def test_search_by_platform_linux(self):
        r = self.search({'platform_ids': [amo.PLATFORM_LINUX.id]})
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), ['Linux Widget'])

    def test_search_by_platform_mac_linux(self):
        r = self.search({'platform_ids': [amo.PLATFORM_MAC.id,
                                          amo.PLATFORM_LINUX.id]})
        eq_(r.status_code, 200)
        eq_(sorted(self.named_addons(r)), ['Linux Widget', 'Mac Widget'])

    def test_search_by_app(self):
        r = self.search({'application_id': [amo.MOBILE.id]})
        eq_(r.status_code, 200)
        eq_(self.named_addons(r), ['Bieber For Mobile'])

    def test_search_by_version_requires_app(self):
        r = self.client.get(self.url, data={'max_version': '3.6'})
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
        VersionSummary.objects.create(application=app,
                                      version=d['version'],
                                      addon=d['addon'],
                                      max=max.id)
        r = self.search({'application_id': amo.MOBILE.id,
                         'max_version': '4.0b2pre'})
        eq_(self.named_addons(r), [u'Bieber For Mobile 4.0b2pre'])

    def test_age_of_submission(self):
        Addon.objects.update(
                nomination_date=datetime.now() - timedelta(days=1))
        bieber = (Addon.objects
                  .filter(name__localized_string='Justin Bieber Persona'))
        # Exclude anything out of range:
        bieber.update(nomination_date=datetime.now() - timedelta(days=5))
        r = self.search({'waiting_time_days': 2})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' not in addons, (
                                'Unexpected results: %r' % addons)
        # Include anything submitted up to requested days:
        bieber.update(nomination_date=datetime.now() - timedelta(days=2))
        r = self.search({'waiting_time_days': 5})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' in addons, (
                                'Unexpected results: %r' % addons)
        # Special case: exclude anything under 10 days:
        bieber.update(nomination_date=datetime.now() - timedelta(days=8))
        r = self.search({'waiting_time_days': '10+'})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' not in addons, (
                                'Unexpected results: %r' % addons)
        # Special case: include anything 10 days and over:
        bieber.update(nomination_date=datetime.now() - timedelta(days=12))
        r = self.search({'waiting_time_days': '10+'})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' in addons, (
                                'Unexpected results: %r' % addons)

    def test_form(self):
        r = self.search({})
        doc = pq(r.content)
        eq_(doc('#id_application_id').attr('data-url'),
            reverse('editors.application_versions_json'))
        eq_(doc('#id_max_version option').text(),
            'Select an application first')
        r = self.search({'application_id': amo.MOBILE.id})
        doc = pq(r.content)
        eq_(doc('#id_max_version option').text(), '4.0b2pre 2.0a1pre 1.0')

    def test_application_versions_json(self):
        r = self.client.post(reverse('editors.application_versions_json'),
                             {'application_id': amo.MOBILE.id})
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['choices'],
            [['', ''],
             ['4.0b2pre', '4.0b2pre'],
             ['2.0a1pre', '2.0a1pre'],
             ['1.0', '1.0']])


class TestQueueSearchVersionSpecific(SearchTest):

    def setUp(self):
        super(TestQueueSearchVersionSpecific, self).setUp()
        self.url = reverse('editors.queue_prelim')
        create_addon_file('Not Admin Reviewed', '0.1',
                          amo.STATUS_LITE, amo.STATUS_UNREVIEWED)
        create_addon_file('Justin Bieber Persona', '0.1',
                          amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                          addon_type=amo.ADDON_THEME)

    def test_age_of_submission(self):
        Version.objects.update(created=datetime.now() - timedelta(days=1))
        bieber = (Version.objects.filter(
                  addon__name__localized_string='Justin Bieber Persona'))
        # Exclude anything out of range:
        bieber.update(created=datetime.now() - timedelta(days=5))
        r = self.search({'waiting_time_days': 2})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' not in addons, (
                                'Unexpected results: %r' % addons)
        # Include anything submitted up to requested days:
        bieber.update(created=datetime.now() - timedelta(days=2))
        r = self.search({'waiting_time_days': 4})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' in addons, (
                                'Unexpected results: %r' % addons)
        # Special case: exclude anything under 10 days:
        bieber.update(created=datetime.now() - timedelta(days=8))
        r = self.search({'waiting_time_days': '10+'})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' not in addons, (
                                'Unexpected results: %r' % addons)
        # Special case: include anything 10 days and over:
        bieber.update(created=datetime.now() - timedelta(days=12))
        r = self.search({'waiting_time_days': '10+'})
        addons = self.named_addons(r)
        assert 'Justin Bieber Persona' in addons, (
                                'Unexpected results: %r' % addons)


class ReviewBase(QueueTest):
    def setUp(self):
        super(ReviewBase, self).setUp()
        self.version = self.versions['Public']
        self.addon = self.version.addon
        self.editor = UserProfile.objects.get(email='editor@mozilla.com')
        self.editor.update(display_name='An editor')
        self.url = reverse('editors.review', args=[self.version.pk])


class TestReview(ReviewBase):
    def setUp(self):
        super(TestReview, self).setUp()
        AddonUser.objects.create(addon=self.addon,
                         user=UserProfile.objects.get(pk=999))

    def test_editor_required(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200)

    def test_not_anonymous(self):
        self.client.logout()
        response = self.client.get(self.url)
        eq_(response.status_code, 302)

    @patch_object(settings._wrapped, 'DEBUG', False)
    def test_not_author(self):
        AddonUser.objects.create(addon=self.addon, user=self.editor)
        response = self.client.get(self.url)
        eq_(response.status_code, 302)

    def test_not_flags(self):
        response = self.client.get(self.url)
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

    def test_info_requested(self):
        response = self.client.post(self.url, {'action': 'info',
                                               'comments': 'hello sailor'})
        eq_(response.status_code, 302)
        eq_(len(mail.outbox), 1)
        self.assertTemplateUsed(response, 'editors/emails/info.ltxt')

    def test_paging_none(self):
        response = self.client.get(self.url)
        eq_(response.context['paging'], {})

    def test_paging_num(self):
        response = self.client.get('%s?num=1' % self.url)
        eq_(response.context['paging']['prev'], False)
        eq_(response.context['paging']['next'], True)
        eq_(response.context['paging']['total'], 2)

        response = self.client.get('%s?num=2' % self.url)
        eq_(response.context['paging']['prev'], True)
        eq_(response.context['paging']['next'], False)


class TestReviewPreliminary(ReviewBase):

    def get_addon(self):
        return Addon.objects.get(pk=self.addon.pk)

    def setUp(self):
        super(TestReviewPreliminary, self).setUp()
        AddonUser.objects.create(addon=self.addon,
                         user=UserProfile.objects.get(pk=999))

    def prelim_dict(self):
        return {'action': 'prelim', 'operating_systems': 'win',
                'applications': 'something', 'comments': 'something',
                'files': [self.version.files.all()[0].pk]}

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
        eq_(response.context['form'].errors['applications'][0],
            'Please enter the applications you tested.')
        eq_(response.context['form'].errors['operating_systems'][0],
            'Please enter the operating systems you tested.')

    def test_prelim_from_lite_no_files(self):
        self.addon.update(status=amo.STATUS_LITE)
        data = self.prelim_dict()
        del data['files']
        response = self.client.post(self.url, data)

        eq_(response.context['form'].errors['files'][0],
            'You must select some files.')

    def test_prelim_from_lite_wrong(self):
        self.addon.update(status=amo.STATUS_LITE)
        response = self.client.post(self.url, self.prelim_dict())

        eq_(response.context['form'].errors['files'][0],
            'File Public.xpi is not pending review.')

    def test_prelim_from_lite_wrong_two(self):
        self.addon.update(status=amo.STATUS_LITE)
        data = self.prelim_dict()
        file = self.version.files.all()[0]
        for status in amo.STATUS_CHOICES:
            if status != amo.STATUS_UNREVIEWED:
                file.update(status=status)
                response = self.client.post(self.url, data)
                eq_(response.context['form'].errors['files'][0],
                    'File Public.xpi is not pending review.')

    def test_prelim_from_lite_files(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.client.post(self.url, data=self.prelim_dict())
        eq_(self.get_addon().status, amo.STATUS_LITE)

    def test_prelim_from_unreviewed(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        response = self.client.post(self.url, self.prelim_dict())
        eq_(response.status_code, 302)
        eq_(self.get_addon().status, amo.STATUS_LITE)

    def test_prelim_multiple_files(self):
        version = self.addon.versions.all()[0]
        file = version.files.all()[0]
        file.pk = None
        file.status = amo.STATUS_DISABLED
        file.save()
        self.addon.update(status=amo.STATUS_LITE)
        data = self.prelim_dict()
        data['files'] = [file.pk]
        self.client.post(self.url, data)
        eq_([amo.STATUS_DISABLED, amo.STATUS_LISTED],
            [v.status for v in version.files.all().order_by('status')])


class TestEditorMOTD(EditorTest):

    def test_change_motd(self):
        self.login_as_admin()
        r = self.client.post(reverse('editors.save_motd'),
                             {'motd': "Let's get crazy"})
        if r.context:
            eq_(r.context['form'].errors.as_text(), "")
        self.assertRedirects(r, reverse('editors.motd'))
        r = self.client.get(reverse('editors.motd'))
        doc = pq(r.content)
        eq_(doc('.daily-message p').text(), "Let's get crazy")

    def test_require_editor_to_view(self):
        r = self.client.get(reverse('editors.motd'))
        eq_(r.status_code, 302)

    def test_require_admin_to_change_motd(self):
        self.login_as_editor()
        r = self.client.post(reverse('editors.save_motd'),
                             {'motd': "I'm a sneaky editor"})
        eq_(r.status_code, 403)

    def test_editor_can_view_not_edit(self):
        set_config('editors_review_motd', 'Some announcement')
        self.login_as_editor()
        r = self.client.get(reverse('editors.motd'))
        doc = pq(r.content)
        eq_(doc('.daily-message p').text(), "Some announcement")
        eq_(r.context['form'], None)

    def test_form_errors(self):
        self.login_as_admin()
        r = self.client.post(reverse('editors.save_motd'), {})
        doc = pq(r.content)
        eq_(doc('#editor-motd .errorlist').text(), 'This field is required.')
