# -*- coding: utf-8 -*-
import datetime
import json

from django.conf import settings

import mock
from pyquery import PyQuery as pq

import amo
import amo.tests
import constants.editors as rvw
from access.models import GroupUser
from addons.models import Persona
from amo.tests import addon_factory, days_ago
from amo.urlresolvers import reverse
from devhub.models import ActivityLog, AddonLog
from editors.models import RereviewQueueTheme, ReviewerScore, ThemeLock
from editors.views_themes import _get_themes, home, themes_search
from users.models import UserProfile


class ThemeReviewTestMixin(object):
    fixtures = ['base/users', 'editors/user_persona_reviewer',
                'editors/user_senior_persona_reviewer']

    def setUp(self):
        super(ThemeReviewTestMixin, self).setUp()
        self.reviewer_count = 0
        self.status = amo.STATUS_PENDING
        self.flagged = False
        self.rereview = False

    def create_and_become_reviewer(self):
        """Login as new reviewer with unique username."""
        username = 'reviewer%s' % self.reviewer_count
        email = username + '@mozilla.com'
        user = UserProfile.objects.create(email=email,
                                          username=username)
        user.set_password('password')
        user.save()
        GroupUser.objects.create(group_id=50060, user=user)

        self.client.login(username=email, password='password')
        self.reviewer_count += 1
        return user

    def theme_factory(self, status=None):
        status = status or self.status
        addon = addon_factory(type=amo.ADDON_PERSONA, status=status)
        if self.rereview:
            RereviewQueueTheme.objects.create(
                theme=addon.persona, header='pending_header',
                footer='pending_footer')
        persona = addon.persona
        persona.persona_id = 0
        persona.header = 'header'
        persona.footer = 'footer'
        persona.save()
        return addon

    def get_themes(self, reviewer):
        return _get_themes(mock.Mock(), reviewer, flagged=self.flagged,
                           rereview=self.rereview)

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_basic_queue(self):
        """
        Have reviewers take themes from the pool,
        check their queue sizes.
        """
        for x in range(rvw.THEME_INITIAL_LOCKS + 1):
            self.theme_factory()

        expected_themes = []
        if self.rereview:
            rrq = RereviewQueueTheme.objects.all()
            expected_themes = [
                [rrq[0], rrq[1]],
                [rrq[2]],
                []
            ]
        else:
            themes = Persona.objects.all()
            expected_themes = [
                [themes[0], themes[1]],
                [themes[2]],
                []
            ]

        for expected in expected_themes:
            reviewer = self.create_and_become_reviewer()
            assert list(self.get_themes(reviewer)) == expected
            assert ThemeLock.objects.filter(reviewer=reviewer).count() == len(expected)

    @mock.patch('amo.messages.success')
    @mock.patch('editors.tasks.reject_rereview')
    @mock.patch('editors.tasks.approve_rereview')
    @mock.patch('addons.tasks.version_changed')
    @mock.patch('editors.tasks.send_mail_jinja')
    @mock.patch('editors.tasks.create_persona_preview_images')
    @mock.patch('amo.storage_utils.copy_stored_file')
    def test_commit(self, copy_mock, create_preview_mock,
                    send_mail_jinja_mock, version_changed_mock,
                    approve_rereview_mock, reject_rereview_mock,
                    message_mock):
        if self.flagged:
            # Feels redundant to test this for flagged queue.
            return

        themes = []
        for x in range(5):
            themes.append(self.theme_factory().persona)
        form_data = amo.tests.formset(initial_count=5, total_count=6)

        # Create locks.
        reviewer = self.create_and_become_reviewer()
        for index, theme in enumerate(themes):
            ThemeLock.objects.create(
                theme=theme, reviewer=reviewer,
                expiry=datetime.datetime.now() +
                datetime.timedelta(minutes=rvw.THEME_LOCK_EXPIRY))
            form_data['form-%s-theme' % index] = str(theme.id)

        # Build formset.
        actions = (
            (str(rvw.ACTION_MOREINFO), 'moreinfo', ''),
            (str(rvw.ACTION_FLAG), 'flag', ''),
            (str(rvw.ACTION_DUPLICATE), 'duplicate', ''),
            (str(rvw.ACTION_REJECT), 'reject', '1'),
            (str(rvw.ACTION_APPROVE), '', ''),
        )
        for index, action in enumerate(actions):
            action, comment, reject_reason = action
            form_data['form-%s-action' % index] = action
            form_data['form-%s-comment' % index] = comment
            form_data['form-%s-reject_reason' % index] = reject_reason

        old_version = themes[4].addon.current_version.version

        # Test edge case where pending theme also has re-review.
        for theme in (themes[3], themes[4]):
            RereviewQueueTheme.objects.create(theme=theme, header='',
                                              footer='')

        # Commit.
        # Activate another locale than en-US, and make sure emails to theme
        # authors are NOT translated, but the message to the review IS.
        with self.activate(locale='fr'):
            res = self.client.post(reverse('editors.themes.commit'), form_data)
            self.assert3xx(res, reverse('editors.themes.queue_themes'))

        if self.rereview:
            # Original design of reuploaded themes should stay public.
            for i in range(4):
                assert themes[i].addon.status == amo.STATUS_PUBLIC
                assert themes[i].header == 'header'
                assert themes[i].footer == 'footer'

            assert copy_mock.call_args_list[0][0][0].endswith('pending_header')
            assert copy_mock.call_args_list[0][0][1].endswith('header')
            assert copy_mock.call_args_list[1][0][0].endswith('pending_footer')
            assert copy_mock.call_args_list[1][0][1].endswith('footer')

            create_preview_args = create_preview_mock.call_args_list[0][1]
            assert create_preview_args['src'].endswith('header')
            assert create_preview_args['full_dst'][0].endswith('preview.png')
            assert create_preview_args['full_dst'][1].endswith('icon.png')
            assert RereviewQueueTheme.objects.count() == 2
            assert themes[4].addon.reload().current_version.version == str(float(old_version) + 1)
        else:
            assert themes[0].addon.reload().status == amo.STATUS_REVIEW_PENDING
            assert themes[1].addon.reload().status == amo.STATUS_REVIEW_PENDING
            assert themes[2].addon.reload().status == amo.STATUS_REJECTED
            assert themes[3].addon.reload().status == amo.STATUS_REJECTED
        assert themes[4].addon.reload().status == amo.STATUS_PUBLIC
        assert ActivityLog.objects.count() == 4 if self.rereview else 5

        expected_calls = [
            mock.call(
                'A question about your Theme submission',
                'editors/themes/emails/moreinfo.html',
                {'reason': None,
                 'comment': u'moreinfo',
                 'theme': themes[0],
                 'reviewer_email': u'reviewer0@mozilla.com',
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([])),
            mock.call(
                'Theme submission flagged for review',
                'editors/themes/emails/flag_reviewer.html',
                {'reason': None,
                 'comment': u'flag',
                 'theme': themes[1],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=[settings.THEMES_EMAIL]),
            mock.call(
                'A problem with your Theme submission',
                'editors/themes/emails/reject.html',
                {'reason': u'Duplicate Submission',
                 'comment': u'duplicate',
                 'theme': themes[2],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([])),
            mock.call(
                'A problem with your Theme submission',
                'editors/themes/emails/reject.html',
                {'reason': u'Sexual or pornographic content',
                 'comment': u'reject',
                 'theme': themes[3],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([])),
            mock.call(
                'Thanks for submitting your Theme',
                'editors/themes/emails/approve.html',
                {'reason': None,
                 'comment': u'',
                 'theme': themes[4],
                 'base_url': 'http://testserver'},
                headers={'Reply-To': settings.THEMES_EMAIL},
                from_email=settings.ADDONS_EMAIL,
                recipient_list=set([]))
        ]
        if self.rereview:
            assert send_mail_jinja_mock.call_args_list[0] == expected_calls[0]
            assert send_mail_jinja_mock.call_args_list[1] == expected_calls[2]
            assert send_mail_jinja_mock.call_args_list[2] == expected_calls[3]
            assert send_mail_jinja_mock.call_args_list[3] == expected_calls[4]
        else:
            assert not approve_rereview_mock.called
            assert not reject_rereview_mock.called
            assert send_mail_jinja_mock.call_args_list[0] == expected_calls[0]
            assert send_mail_jinja_mock.call_args_list[1] == expected_calls[1]
            assert send_mail_jinja_mock.call_args_list[2] == expected_calls[2]
            assert send_mail_jinja_mock.call_args_list[3] == expected_calls[3]
            assert send_mail_jinja_mock.call_args_list[4] == expected_calls[4]
            assert message_mock.call_args_list[0][0][1] == u'5 validation de thèmes réalisées avec succès ' u'(+15 points, 15 au total).'

        # Reviewer points accrual.
        assert ReviewerScore.objects.all()[0].score > 0

    def test_single_basic(self):
        with self.settings(ALLOW_SELF_REVIEWS=True):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = self.theme_factory()

            res = self.client.get(reverse('editors.themes.single',
                                          args=[addon.slug]))
            assert res.status_code == 200
            assert res.context['theme'].id == addon.persona.rereviewqueuetheme_set.all()[0].id if self.rereview else addon.persona.id
            assert res.context['reviewable'] == (not self.flagged)


class TestThemeQueue(ThemeReviewTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestThemeQueue, self).setUp()
        self.queue_url = reverse('editors.themes.queue_themes')

    def check_permissions(self, slug, status_code):
        for url in [reverse('editors.themes.queue_themes'),
                    reverse('editors.themes.single', args=[slug])]:
            assert self.client.get(url).status_code == status_code

    def test_permissions_reviewer(self):
        slug = self.theme_factory().slug

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
            addon = self.theme_factory()

            res = self.client.get(self.queue_url)
            assert len(res.context['theme_formsets']) == 1
            assert res.context['theme_formsets'][0][0] == addon.persona

    def test_cannot_review_my_app(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = self.theme_factory()
            addon.addonuser_set.create(user=user)

            res = self.client.get(self.queue_url)
            assert len(res.context['theme_formsets']) == 0

    def test_theme_list(self):
        self.create_and_become_reviewer()
        self.theme_factory()
        res = self.client.get(reverse('editors.themes.list'))
        assert res.status_code == 200
        assert pq(res.content)('#addon-queue tbody tr').length == 1

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 1)
    def test_release_locks(self):
        for x in range(2):
            addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        other_reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), other_reviewer)

        # Check reviewer's theme lock released.
        reviewer = self.create_and_become_reviewer()
        _get_themes(mock.Mock(), reviewer)
        assert ThemeLock.objects.filter(reviewer=reviewer).count() == 1
        self.client.get(reverse('editors.themes.release_locks'))
        assert ThemeLock.objects.filter(reviewer=reviewer).count() == 0
        assert ThemeLock.objects.filter(reviewer=other_reviewer).count() == 1

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_themes_less_than_initial(self):
        """
        Number of themes in the pool is less than amount we want to check out.
        """
        addon_factory(type=amo.ADDON_PERSONA, status=self.status)
        reviewer = self.create_and_become_reviewer()
        assert len(_get_themes(mock.Mock(), reviewer)) == 1
        assert len(_get_themes(mock.Mock(), reviewer)) == 1

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_top_off(self):
        """If reviewer has fewer than max locks, get more from pool."""
        for x in range(2):
            self.theme_factory()
        reviewer = self.create_and_become_reviewer()
        self.get_themes(reviewer)
        ThemeLock.objects.filter(reviewer=reviewer)[0].delete()
        self.get_themes(reviewer)
        assert ThemeLock.objects.filter(reviewer=reviewer).count() == rvw.THEME_INITIAL_LOCKS

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_expiry(self):
        """
        Test that reviewers who want themes from an empty pool can steal
        checked-out themes from other reviewers whose locks have expired.
        """
        for x in range(2):
            self.theme_factory(status=self.status)
        reviewer = self.create_and_become_reviewer()
        self.get_themes(reviewer)

        # Reviewer wants themes, but empty pool.
        reviewer = self.create_and_become_reviewer()
        self.get_themes(reviewer)
        assert ThemeLock.objects.filter(reviewer=reviewer).count() == 0

        # Manually expire a lock and see if it's reassigned.
        expired_theme_lock = ThemeLock.objects.all()[0]
        expired_theme_lock.expiry = self.days_ago(1)
        expired_theme_lock.save()
        self.get_themes(reviewer)
        assert ThemeLock.objects.filter(reviewer=reviewer).count() == 1

    def test_expiry_update(self):
        """Test expiry is updated when reviewer reloads his queue."""
        self.theme_factory()
        reviewer = self.create_and_become_reviewer()
        self.get_themes(reviewer)

        ThemeLock.objects.filter(reviewer=reviewer).update(expiry=days_ago(1))
        _get_themes(mock.Mock(), reviewer, flagged=self.flagged)
        self.get_themes(reviewer)
        assert ThemeLock.objects.filter(reviewer=reviewer)[0].expiry > days_ago(1) is True

    def test_user_review_history(self):
        self.theme_factory()

        reviewer = self.create_and_become_reviewer()

        res = self.client.get(reverse('editors.themes.history'))
        assert res.status_code == 200
        doc = pq(res.content)
        assert doc('tbody tr').length == 0

        theme = Persona.objects.all()[0]
        for x in range(3):
            amo.log(amo.LOG.THEME_REVIEW, theme.addon, user=reviewer,
                    details={'action': rvw.ACTION_APPROVE,
                             'comment': '', 'reject_reason': ''})

        res = self.client.get(reverse('editors.themes.history'))
        assert res.status_code == 200
        doc = pq(res.content)
        assert doc('tbody tr').length == 3

        res = self.client.get(reverse('editors.themes.logs'))
        assert res.status_code == 200
        doc = pq(res.content)
        assert doc('tbody tr').length == 3 * 2  # Double for comment rows.

    def test_single_cannot_review_own_theme(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            user = UserProfile.objects.get(
                email='persona_reviewer@mozilla.com')
            self.login(user)
            addon = self.theme_factory()
            addon.addonuser_set.create(user=user)

            res = self.client.get(reverse('editors.themes.single',
                                          args=[addon.slug]))
            assert res.status_code == 200
            assert res.context['theme'].id == addon.persona.rereviewqueuetheme_set.all()[0].id if self.rereview else addon.persona.id
            assert res.context['reviewable'] is False

    @mock.patch.object(rvw, 'THEME_INITIAL_LOCKS', 2)
    def test_queue_cannot_review_own_theme(self):
        with self.settings(ALLOW_SELF_REVIEWS=False):
            reviewer = self.create_and_become_reviewer()

            for x in range(rvw.THEME_INITIAL_LOCKS + 1):
                addon = self.theme_factory()
                addon.addonuser_set.create(user=reviewer)
            assert _get_themes(amo.tests.req_factory_factory('', reviewer), reviewer) == []
            assert ThemeLock.objects.filter(reviewer=reviewer).count() == 0


class TestThemeQueueFlagged(ThemeReviewTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestThemeQueueFlagged, self).setUp()
        self.status = amo.STATUS_REVIEW_PENDING
        self.flagged = True
        self.queue_url = reverse('editors.themes.queue_flagged')

    def test_admin_only(self):
        self.login('persona_reviewer@mozilla.com')
        assert self.client.get(self.queue_url).status_code == 403

        self.login('senior_persona_reviewer@mozilla.com')
        assert self.client.get(self.queue_url).status_code == 200


class TestThemeQueueRereview(ThemeReviewTestMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestThemeQueueRereview, self).setUp()
        self.status = amo.STATUS_PUBLIC
        self.rereview = True
        self.queue_url = reverse('editors.themes.queue_rereview')

    def test_admin_only(self):
        self.login('persona_reviewer@mozilla.com')
        assert self.client.get(self.queue_url).status_code == 403

        self.login('senior_persona_reviewer@mozilla.com')
        assert self.client.get(self.queue_url).status_code == 200

    def test_soft_deleted_addon(self):
        """
        Test soft-deleted add-ons don't cause trouble like they did to me
        for the last 6 months! #liberation
        """
        # Normal RQT object.
        theme = addon_factory(type=amo.ADDON_PERSONA)
        RereviewQueueTheme.objects.create(header='', footer='',
                                          theme=theme.persona)

        # Deleted add-on RQT object.
        theme = addon_factory(type=amo.ADDON_PERSONA)
        RereviewQueueTheme.objects.create(header='', footer='',
                                          theme=theme.persona)
        theme.delete()

        self.login('senior_persona_reviewer@mozilla.com')
        r = self.client.get(self.queue_url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('.theme').length == 1
        assert RereviewQueueTheme.unfiltered.count() == 2

    def test_rejected_addon_in_rqt(self):
        """Test rejected addons in RQT are not displayed in review lists."""
        self.theme_factory(status=amo.STATUS_PUBLIC)
        self.theme_factory(status=amo.STATUS_REJECTED)
        self.login('senior_persona_reviewer@mozilla.com')
        r = self.client.get(self.queue_url)
        assert r.status_code == 200
        assert pq(r.content)('.theme').length == 1

    def test_rejected_addon_in_locks(self):
        """Test rejected addons in locks are not displayed in review lists."""
        reviewer = UserProfile.objects.get(
            email='persona_reviewer@mozilla.com')
        # Either public or rejected locked themes should not showing up.
        public_theme = self.theme_factory(status=amo.STATUS_PUBLIC)
        ThemeLock.objects.create(reviewer=reviewer, expiry=self.days_ago(-1),
                                 theme=public_theme.persona)
        rejected_theme = self.theme_factory(status=amo.STATUS_REJECTED)
        ThemeLock.objects.create(reviewer=reviewer, expiry=self.days_ago(-1),
                                 theme=rejected_theme.persona)
        self.login('senior_persona_reviewer@mozilla.com')
        r = self.client.get(self.queue_url)
        assert r.status_code == 200
        assert pq(r.content)('.theme').length == 0

    @mock.patch('editors.tasks.send_mail_jinja')
    @mock.patch('editors.tasks.copy_stored_file')
    @mock.patch('editors.tasks.create_persona_preview_images')
    @mock.patch('amo.storage_utils.copy_stored_file')
    def test_update_legacy_theme(self, copy_mock, prev_mock, copy_mock2,
                                 noop3):
        """
        Test updating themes that were submitted from GetPersonas.
        STR the bug this test fixes:

        - Reupload a legacy theme and approve it.
        - On approving, it would make a preview image with the destination as
         'preview.png' and 'icon.png', but legacy themes use
         'preview.jpg' and 'preview_small.jpg'.
        - Thus the preview images were not being updated, but the header/footer
          images were.
        """
        theme = self.theme_factory(status=amo.STATUS_PUBLIC).persona
        theme.header = 'Legacy-header3H.png'
        theme.footer = 'Legacy-footer3H-Copy.jpg'
        theme.persona_id = 5
        theme.save()
        form_data = amo.tests.formset(initial_count=5, total_count=6)

        RereviewQueueTheme.objects.create(
            theme=theme, header='pending_header.png',
            footer='pending_footer.png')

        # Create lock.
        reviewer = self.create_and_become_reviewer()
        ThemeLock.objects.create(
            theme=theme, reviewer=reviewer, expiry=self.days_ago(-1))
        form_data['form-0-theme'] = str(theme.id)

        # Build formset.
        form_data['form-0-action'] = str(rvw.ACTION_APPROVE)

        # Commit.
        self.client.post(reverse('editors.themes.commit'), form_data)
        assert theme.header == 'Legacy-header3H.png'
        assert theme.footer == 'Legacy-footer3H-Copy.jpg'
        theme.thumb_path.endswith('preview.jpg')
        theme.icon_path.endswith('preview_small.jpg')
        theme.preview_path.endswith('preview_large.jpg')

        # Test calling create_persona_preview_images.
        assert (prev_mock.call_args_list[0][1]['full_dst'][0]
                .endswith('preview.jpg'))
        assert (prev_mock.call_args_list[0][1]['full_dst'][1]
                .endswith('preview_small.jpg'))

        # pending_header should be mv'ed to Legacy-header3H.png.
        assert copy_mock.call_args_list[0][0][0].endswith('pending_header')
        assert (copy_mock.call_args_list[0][0][1]
                .endswith('Legacy-header3H.png'))
        # pending_footer should be mv'ed to Legacy-footer-Copy3H.png.
        assert (copy_mock.call_args_list[1][0][0]
                .endswith('pending_footer'))
        assert (copy_mock.call_args_list[1][0][1]
                .endswith('Legacy-footer3H-Copy.jpg'))

        assert (copy_mock2.call_args_list[0][0][0]
                .endswith('preview.jpg'))
        assert (copy_mock2.call_args_list[0][0][1]
                .endswith('preview_large.jpg'))

    def test_single_rejected_reason_9_bug_1140346(self):
        """Can rereview an updated theme that was rejected for reason 9."""
        user = UserProfile.objects.get(email='persona_reviewer@mozilla.com')
        self.login(user)
        addon = self.theme_factory(status=amo.STATUS_REJECTED)
        RereviewQueueTheme.objects.create(
            theme=addon.persona, header='pending_header.png',
            footer='pending_footer.png')
        AddonLog.objects.create(
            addon=addon,
            activity_log=ActivityLog.objects.create(
                user=user, action=amo.LOG.THEME_REVIEW.id,
                _arguments=str(addon.pk),
                details={'action': 4, 'reject_reason': 9}))

        with self.settings(ALLOW_SELF_REVIEWS=True):
            res = self.client.get(reverse('editors.themes.single',
                                          args=[addon.slug]))
        assert res.status_code == 200

    @mock.patch('amo.utils.LocalFileStorage.delete')
    def test_reject_theme_without_footer_bug_1142449(self, delete_mock):
        """Don't fail on trying to deleted a non existent footer image."""
        user = UserProfile.objects.get(email='persona_reviewer@mozilla.com')
        self.login(user)
        theme = self.theme_factory().persona
        reject_url = reverse('editors.themes.commit')

        form_data = amo.tests.formset(initial_count=1, total_count=1)
        form_data['form-0-theme'] = str(theme.pk)
        form_data['form-0-action'] = str(rvw.ACTION_REJECT)
        form_data['form-0-reject_reason'] = 1

        # With footer (RereviewQueueTheme created in theme_factory has one).
        rereview = theme.rereviewqueuetheme_set.first()
        ThemeLock.objects.create(theme=theme, reviewer=user,
                                 expiry=self.days_ago(-1))

        with self.settings(ALLOW_SELF_REVIEWS=True):
            res = self.client.post(reject_url, form_data)
        assert res.status_code == 302
        assert delete_mock.call_count == 2  # Did try to delete the footer.
        delete_mock.assert_any_call(rereview.header_path)
        delete_mock.assert_any_call(rereview.footer_path)

        delete_mock.reset_mock()  # Clean slate.

        # Without footer.
        rereview = RereviewQueueTheme.objects.create(
            theme=theme, header='pending_header.png')
        ThemeLock.objects.create(theme=theme, reviewer=user,
                                 expiry=self.days_ago(-1))

        with self.settings(ALLOW_SELF_REVIEWS=True):
            res = self.client.post(reject_url, form_data)
        assert res.status_code == 302
        assert delete_mock.call_count == 1  # Didn't try to delete the footer.
        delete_mock.assert_any_call(rereview.header_path)


class TestDeletedThemeLookup(amo.tests.TestCase):
    fixtures = ['base/users', 'editors/user_persona_reviewer',
                'editors/user_senior_persona_reviewer']

    def setUp(self):
        super(TestDeletedThemeLookup, self).setUp()
        self.deleted = addon_factory(type=amo.ADDON_PERSONA)
        self.deleted.update(status=amo.STATUS_DELETED)

    def test_table(self):
        self.login('senior_persona_reviewer@mozilla.com')
        r = self.client.get(reverse('editors.themes.deleted'))
        assert r.status_code == 200
        assert pq(r.content)('tbody td:nth-child(3)').text() == self.deleted.name.localized_string

    def test_perm(self):
        self.login('persona_reviewer@mozilla.com')
        r = self.client.get(reverse('editors.themes.deleted'))
        assert r.status_code == 403


class TestThemeSearch(amo.tests.ESTestCase):
    fixtures = ['editors/user_senior_persona_reviewer']

    def setUp(self):
        super(TestThemeSearch, self).setUp()
        self.addon = addon_factory(type=amo.ADDON_PERSONA, name='themeteam',
                                   status=amo.STATUS_PENDING)
        self.refresh('default')

    def search(self, q, flagged=False, rereview=False):
        get_query = {'q': q, 'queue_type': ('rereview' if rereview else
                                            'flagged' if flagged else '')}

        request = amo.tests.req_factory_factory(
            reverse('editors.themes.search'),
            user=UserProfile.objects.get(username='senior_persona_reviewer'))
        request.GET = get_query
        return json.loads(themes_search(request).content)['objects']

    def test_pending(self):
        assert self.search('theme')[0]['id'] == self.addon.id

    def test_flagged(self):
        self.addon.update(status=amo.STATUS_REVIEW_PENDING)
        self.refresh('default')
        assert self.search('theme', flagged=True)[0]['id'] == self.addon.id

    def test_rereview(self):
        RereviewQueueTheme.objects.create(theme=self.addon.persona)
        self.addon.save()
        self.refresh('default')
        assert self.search('theme', rereview=True)[0]['id'] == self.addon.id


class TestDashboard(amo.tests.TestCase):
    fixtures = ['editors/user_senior_persona_reviewer']

    def setUp(self):
        super(TestDashboard, self).setUp()
        self.request = amo.tests.req_factory_factory(
            reverse('editors.themes.home'), user=UserProfile.objects.get())

    def test_dashboard_queue_counts(self):
        # Pending.
        addon_factory(type=amo.ADDON_PERSONA,
                      status=amo.STATUS_PENDING)
        for i in range(2):
            # Flagged.
            addon_factory(type=amo.ADDON_PERSONA,
                          status=amo.STATUS_REVIEW_PENDING)
        # Rereview.
        rereview = addon_factory(type=amo.ADDON_PERSONA,
                                 status=amo.STATUS_PUBLIC)
        RereviewQueueTheme.objects.create(theme=rereview.persona)

        r = home(self.request)
        assert r.status_code == 200

        doc = pq(r.content)
        titles = doc('#editors-stats-charts .editor-stats-title a')
        assert titles[0].text.strip()[0] == '1'  # Pending count.
        assert titles[1].text.strip()[0] == '2'  # Flagged count.
        assert titles[2].text.strip()[0] == '1'  # Rereview count.

    def test_dashboard_review_counts(self):
        theme = addon_factory(type=amo.ADDON_PERSONA)
        for i in range(3):
            amo.log(amo.LOG.THEME_REVIEW, theme,
                    user=UserProfile.objects.get())

        r = home(self.request)
        assert r.status_code == 200

        doc = pq(r.content)
        assert doc('.editor-stats-table:first-child td.int').text() == '3'
        assert doc('.editor-stats-table:last-child td.int').text() == '3'


class TestXssOnThemeName(amo.tests.TestXss):

    def setUp(self):
        super(TestXssOnThemeName, self).setUp()
        self.theme = addon_factory(type=amo.ADDON_PERSONA,
                                   status=amo.STATUS_PENDING,
                                   name=self.name)
        persona = self.theme.persona
        persona.persona_id = 0
        persona.header = 'header'
        persona.footer = 'footer'
        persona.save()

    def test_queue_page(self):
        url = reverse('editors.themes.single', args=[self.theme.slug])
        self.assertNameAndNoXSS(url)
