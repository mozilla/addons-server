# -*- coding: utf-8 -*-
import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.test.client import RequestFactory

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from access.models import GroupUser
from addons.models import Persona
import amo
import amo.tests
from amo.tests import addon_factory, days_ago
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
import mkt.constants.reviewers as rvw
from mkt.reviewers.models import ThemeLock
from mkt.reviewers.views_themes import _get_themes
from mkt.site.fixtures import fixture
from users.models import UserProfile


class ThemeReviewTestMixin(object):
    fixtures = fixture('group_admin', 'user_admin', 'user_admin_group',
                       'user_persona_reviewer', 'user_999')

    def setUp(self):
        self.reviewer_count = 0
        self.create_switch(name='mkt-themes')
        self.status = amo.STATUS_PENDING
        self.flagged = False

    def req_factory_factory(self, user, url):
        req = RequestFactory().get(reverse(url))
        req.user = user.user
        req.groups = req.user.get_profile().groups.all()
        req.TABLET = True
        return req

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
        GroupUser.objects.create(group_id=50060, user=user)

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
            addon_factory(type=amo.ADDON_PERSONA, status=self.status)

        themes = Persona.objects.all()
        expected_themes = [
            [themes[0], themes[1]],
            [themes[2]],
            []
        ]

        for expected in expected_themes:
            reviewer = self.create_and_become_reviewer()
            eq_(_get_themes(mock.Mock(), reviewer, flagged=self.flagged),
                expected)
            eq_(ThemeLock.objects.filter(reviewer=reviewer).count(),
                len(expected))

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_top_off(self):
        """If reviewer has fewer than max locks, get more from pool."""
        for x in range(2):
            addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)
        ThemeLock.objects.filter(reviewer=reviewer)[0].delete()
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)

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
            addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)

        # Reviewer wants themes, but empty pool.
        reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(), 0)

        # Manually expire a lock and see if it's reassigned.
        expired_theme_lock = ThemeLock.objects.all()[0]
        expired_theme_lock.expiry = self.days_ago(1)
        expired_theme_lock.save()
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(), 1)

    def test_expiry_update(self):
        """Test expiry is updated when reviewer reloads his queue."""
        addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)

        ThemeLock.objects.filter(reviewer=reviewer).update(expiry=days_ago(1))
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)
        eq_(ThemeLock.objects.filter(reviewer=reviewer)[0].expiry >
            days_ago(1), True)

    @mock.patch('mkt.reviewers.tasks.send_mail_jinja')
    def test_commit(self, send_mail_jinja_mock):
        for x in range(5):
            addon_factory(type=amo.ADDON_PERSONA, status=self.status)

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
        form_data['form-%s-reject_reason' % 3] = '1'

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

        expected_calls = [
            mock.call('A question about your Theme submission',
                'reviewers/themes/emails/moreinfo.html',
                {'reason': None,
                 'comment': u'moreinfo',
                 'theme': themes[0],
                 'reviewer_email': u'reviewer0@mozilla.com',
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([]), cc=settings.THEMES_EMAIL),
            mock.call('Theme submission flagged for review',
                'reviewers/themes/emails/flag_reviewer.html',
                {'reason': None,
                 'comment': u'flag',
                 'theme': themes[1],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=[settings.THEMES_EMAIL], cc=None),
            mock.call('A problem with your Theme submission',
                'reviewers/themes/emails/reject.html',
                {'reason': mock.ANY,
                 'comment': u'duplicate',
                 'theme': themes[2],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([]), cc=settings.THEMES_EMAIL),
            mock.call('A problem with your Theme submission',
                'reviewers/themes/emails/reject.html',
                {'reason': mock.ANY,
                 'comment': u'reject',
                 'theme': themes[3],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([]), cc=settings.THEMES_EMAIL),
            mock.call('Thanks for submitting your Theme',
                'reviewers/themes/emails/approve.html',
                {'reason': None,
                 'comment': u'',
                 'theme': themes[4],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([]), cc=settings.THEMES_EMAIL)
        ]
        eq_(send_mail_jinja_mock.call_args_list[0], expected_calls[0])
        eq_(send_mail_jinja_mock.call_args_list[1], expected_calls[1])
        eq_(send_mail_jinja_mock.call_args_list[2], expected_calls[2])
        eq_(send_mail_jinja_mock.call_args_list[3], expected_calls[3])
        eq_(send_mail_jinja_mock.call_args_list[4], expected_calls[4])

    def test_user_review_history(self):
        addon_factory(type=amo.ADDON_PERSONA, status=self.status)

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
        with self.settings(ALLOW_SELF_REVIEWS=True):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = addon_factory(type=amo.ADDON_PERSONA, status=self.status)

            res = self.client.get(reverse('reviewers.themes.single',
                                          args=[addon.slug]))
            eq_(res.status_code, 200)
            eq_(res.context['theme'].id, addon.persona.id)
            eq_(res.context['reviewable'], not self.flagged)

    def test_single_cannot_review_my_app(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = addon_factory(type=amo.ADDON_PERSONA, status=self.status)

            addon.addonuser_set.create(user=user)

            res = self.client.get(reverse('reviewers.themes.single',
                                          args=[addon.slug]))
            eq_(res.status_code, 200)
            eq_(res.context['theme'].id, addon.persona.id)
            eq_(res.context['reviewable'], False)


class TestThemeReviewQueue(ThemeReviewTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestThemeReviewQueue, self).setUp()
        self.queue_url = reverse('reviewers.themes.queue_themes')

    def check_permissions(self, slug, status_code):
        for url in [reverse('reviewers.themes.queue_themes'),
                    reverse('reviewers.themes.single', args=[slug])]:
            eq_(self.client.get(url).status_code, status_code)

    def test_permissions_reviewer(self):
        slug = addon_factory(type=amo.ADDON_PERSONA, status=self.status).slug

        self.assertLoginRedirects(self.client.get(self.queue_url),
                                  self.queue_url)

        self.login('regular@mozilla.com')
        self.check_permissions(slug, 403)

        self.create_and_become_reviewer()
        self.check_permissions(slug, 200)

    def test_can_review_your_app(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = addon_factory(type=amo.ADDON_PERSONA, status=self.status)

            res = self.client.get(self.queue_url)
            eq_(len(res.context['theme_formsets']), 1)
            # I should be able to review this app. It is not mine.
            eq_(res.context['theme_formsets'][0][0], addon.persona)

    def test_cannot_review_my_app(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = addon_factory(type=amo.ADDON_PERSONA, status=self.status)

            addon.addonuser_set.create(user=user)

            res = self.client.get(self.queue_url)
            # I should not be able to review my own app.
            eq_(len(res.context['theme_formsets']), 0)

    def test_theme_list(self):
        self.create_and_become_reviewer()
        addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        res = self.client.get(reverse('reviewers.themes.list'))
        eq_(res.status_code, 200)
        eq_(pq(res.content)('#addon-queue tbody tr').length, 1)

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 1)
    def test_release_locks(self):
        for x in range(2):
            addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        other_reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), other_reviewer)

        # Check reviewer's theme lock released.
        reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), reviewer)
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(), 1)
        self.client.get(reverse('reviewers.themes.release_locks'))
        eq_(ThemeLock.objects.filter(reviewer=reviewer).count(), 0)

        # Check other reviewer's theme lock intact.
        eq_(ThemeLock.objects.filter(reviewer=other_reviewer).count(), 1)


class TestThemeReviewQueueFlagged(ThemeReviewTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestThemeReviewQueueFlagged, self).setUp()
        self.status = amo.STATUS_REVIEW_PENDING
        self.flagged = True
        self.queue_url = reverse('reviewers.themes.queue_flagged')

    def test_admin_only(self):
        self.login('persona_reviewer@mozilla.com')
        eq_(self.client.get(self.queue_url).status_code, 403)

        self.login('admin@mozilla.com')
        eq_(self.client.get(self.queue_url).status_code, 200)
