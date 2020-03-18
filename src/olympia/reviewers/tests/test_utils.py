# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from unittest import mock
from unittest.mock import Mock, patch

import pytest
import responses
from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.utils import translation
from olympia import amo
from olympia.activity.models import ActivityLog, ActivityLogToken
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonReviewerFlags)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase, addon_factory, file_factory, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.blocklist.models import Block, BLSubmission
from olympia.discovery.models import DiscoveryItem
from olympia.files.models import File
from olympia.lib.crypto.tests.test_signing import (
    _get_recommendation_data, _get_signature_details)
from olympia.reviewers.models import (
    AutoApprovalSummary, ReviewerScore, ViewExtensionQueue)
from olympia.reviewers.utils import (
    ReviewAddon, ReviewFiles, ReviewHelper, ReviewUnlisted,
    ViewUnlistedAllListTable, view_table_factory)
from olympia.users.models import UserProfile
from pyquery import PyQuery as pq


pytestmark = pytest.mark.django_db


REVIEW_FILES_STATUSES = (amo.STATUS_APPROVED, amo.STATUS_DISABLED)


class TestViewExtensionQueueTable(TestCase):

    def setUp(self):
        super().setUp()
        self.table = view_table_factory(ViewExtensionQueue)([])

    def test_addon_name(self):
        row = Mock()
        page = Mock()
        page.start_index = Mock()
        page.start_index.return_value = 1
        row.addon_name = u'フォクすけといっしょ'
        row.addon_slug = 'test'
        row.latest_version = u'0.12'
        self.table.set_page(page)
        a = pq(self.table.render_addon_name(row))

        assert a.attr('href') == (
            reverse('reviewers.review', args=[str(row.addon_slug)]))
        assert a.text() == u"フォクすけといっしょ 0.12"

    def test_addon_type_id(self):
        row = Mock()
        row.addon_type_id = amo.ADDON_SEARCH
        assert str(self.table.render_addon_type_id(row)) == (
            u'Search Engine')

    def test_waiting_time_in_days(self):
        row = Mock()
        row.waiting_time_days = 10
        row.waiting_time_hours = 10 * 24
        assert self.table.render_waiting_time_min(row) == u'10 days'

    def test_waiting_time_one_day(self):
        row = Mock()
        row.waiting_time_days = 1
        row.waiting_time_hours = 24
        row.waiting_time_min = 60 * 24
        assert self.table.render_waiting_time_min(row) == u'1 day'

    def test_waiting_time_in_hours(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 22
        row.waiting_time_min = 60 * 22
        assert self.table.render_waiting_time_min(row) == u'22 hours'

    def test_waiting_time_in_min(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 0
        row.waiting_time_min = 11
        assert self.table.render_waiting_time_min(row) == u'11 minutes'

    def test_waiting_time_in_secs(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 0
        row.waiting_time_min = 0
        assert self.table.render_waiting_time_min(row) == u'moments ago'

    def test_flags(self):
        row = Mock()
        row.flags = [('admin-review', 'Admin Review')]
        doc = pq(self.table.render_flags(row))
        assert doc('div.ed-sprite-admin-review').length


class TestUnlistedViewAllListTable(TestCase):

    def setUp(self):
        super(TestUnlistedViewAllListTable, self).setUp()
        self.table = ViewUnlistedAllListTable([])

    def test_addon_name(self):
        row = Mock()
        page = Mock()
        page.start_index = Mock()
        page.start_index.return_value = 1
        row.addon_name = u'フォクすけといっしょ'
        row.addon_slug = 'test'
        self.table.set_page(page)
        a = pq(self.table.render_addon_name(row))

        assert (a.attr('href') == reverse(
            'reviewers.review', args=['unlisted', str(row.addon_slug)]))
        assert a.text() == u'フォクすけといっしょ'

    def test_authors_few(self):
        row = Mock()
        row.authors = [(123, 'bob'), (456, 'steve')]
        doc = pq(self.table.render_authors(row))
        assert doc('span').text() == 'bob steve'
        assert doc('span a:eq(0)').attr('href') == UserProfile.create_user_url(
            123)
        assert doc('span a:eq(1)').attr('href') == UserProfile.create_user_url(
            456)
        assert doc('span').attr('title') == 'bob steve'

    def test_authors_four(self):
        row = Mock()
        row.authors = [(123, 'bob'), (456, 'steve'), (789, 'cvan'),
                       (999, 'basta')]
        doc = pq(self.table.render_authors(row))
        assert doc.text() == 'bob steve cvan ...'
        assert doc('span a:eq(0)').attr('href') == UserProfile.create_user_url(
            123)
        assert doc('span a:eq(1)').attr('href') == UserProfile.create_user_url(
            456)
        assert doc('span a:eq(2)').attr('href') == UserProfile.create_user_url(
            789)
        assert doc('span').attr('title') == 'bob steve cvan basta', doc.html()


yesterday = datetime.today() - timedelta(days=1)


class TestReviewHelperBase(TestCase):
    __test__ = False

    fixtures = ['base/addon_3615', 'base/users']
    preamble = 'Mozilla Add-ons: Delicious Bookmarks 2.1.072'

    def setUp(self):
        super().setUp()

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482)

        self.request = FakeRequest()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.files.all()[0]

        self.create_paths()

    def _check_score(self, reviewed_type, bonus=0):
        scores = ReviewerScore.objects.all()
        assert len(scores) > 0
        assert scores[0].score == amo.REVIEWED_SCORES[reviewed_type] + bonus
        assert scores[0].note_key == reviewed_type

    def remove_paths(self):
        for path in (self.file.file_path, self.file.guarded_file_path):
            if not storage.exists(path):
                storage.delete(path)

    def create_paths(self):
        for path in (self.file.file_path, self.file.guarded_file_path):
            if not storage.exists(path):
                with storage.open(path, 'w') as f:
                    f.write('test data\n')
        self.addCleanup(self.remove_paths)

    def setup_data(self, status, file_status=amo.STATUS_AWAITING_REVIEW,
                   channel=amo.RELEASE_CHANNEL_LISTED,
                   content_review=False, type=amo.ADDON_EXTENSION):
        mail.outbox = []
        ActivityLog.objects.for_addons(self.helper.addon).delete()
        self.addon.update(status=status, type=type)
        self.file.update(status=file_status)
        if channel == amo.RELEASE_CHANNEL_UNLISTED:
            self.make_addon_unlisted(self.addon)
            self.version.reload()
            self.file.reload()
        self.helper = self.get_helper(content_review=content_review)
        data = self.get_data().copy()
        self.helper.set_data(data)

    def get_data(self):
        return {
            'comments': 'foo',
            'action': 'public',
            'operating_systems': 'osx',
            'applications': 'Firefox',
            'info_request': self.addon.pending_info_request
        }

    def get_helper(self, content_review=False):
        return ReviewHelper(
            request=self.request, addon=self.addon, version=self.version,
            content_review=content_review)

    def setup_type(self, status):
        self.addon.update(status=status)
        return self.get_helper().handler.review_type

    def check_log_count(self, id):
        return (ActivityLog.objects.for_addons(self.helper.addon)
                                   .filter(action=id).count())


# Those tests can call signing when making things public. We want to test that
# it works correctly, so we set ENABLE_ADDON_SIGNING to True and mock the
# actual signing call.
@override_settings(ENABLE_ADDON_SIGNING=True)
@mock.patch('olympia.lib.crypto.signing.call_signing', lambda f: None)
class TestReviewHelper(TestReviewHelperBase):
    __test__ = True

    def test_no_request(self):
        self.request = None
        helper = self.get_helper()
        assert helper.content_review is False
        assert helper.actions == {}

        helper = self.get_helper(content_review=True)
        assert helper.content_review is True
        assert helper.actions == {}

    def test_type_nominated(self):
        assert self.setup_type(amo.STATUS_NOMINATED) == 'extension_nominated'

    def test_type_pending(self):
        assert self.setup_type(amo.STATUS_NULL) == 'extension_pending'
        assert self.setup_type(amo.STATUS_APPROVED) == 'extension_pending'
        assert self.setup_type(amo.STATUS_DISABLED) == 'extension_pending'

    def test_no_version(self):
        helper = ReviewHelper(
            request=self.request, addon=self.addon, version=None)
        assert helper.handler.review_type == 'extension_pending'

    def test_review_files(self):
        version_factory(addon=self.addon,
                        created=self.version.created - timedelta(days=1),
                        file_kw={'status': amo.STATUS_APPROVED})
        for status in REVIEW_FILES_STATUSES:
            self.setup_data(status=status)
            assert self.helper.handler.__class__ == ReviewFiles

    def test_review_addon(self):
        self.setup_data(status=amo.STATUS_NOMINATED)
        assert self.helper.handler.__class__ == ReviewAddon

    def test_process_action_none(self):
        self.helper.set_data({'action': 'foo'})
        with self.assertRaises(Exception):
            self.helper.process()

    def test_process_action_good(self):
        self.grant_permission(self.request.user, 'Addons:PostReview')
        self.helper = self.get_helper()
        self.helper.set_data({'action': 'reply', 'comments': 'foo'})
        self.helper.process()
        assert len(mail.outbox) == 1

    def test_action_details(self):
        for status in Addon.STATUS_CHOICES:
            self.addon.update(status=status)
            helper = self.get_helper()
            actions = helper.actions
            for k, v in actions.items():
                assert str(v['details']), "Missing details for: %s" % k

    def get_review_actions(
            self, addon_status, file_status, content_review=False):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        # Need to clear self.version.all_files cache since we updated the file.
        if self.version:
            del self.version.all_files
        return self.get_helper(content_review=content_review).actions

    def test_actions_full_nominated(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        expected = ['public', 'reject', 'reject_multiple_versions', 'reply',
                    'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW).keys()) == expected

    def test_actions_full_update(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        expected = ['public', 'reject', 'reject_multiple_versions', 'reply',
                    'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_AWAITING_REVIEW).keys()) == expected

    def test_actions_full_nonpending(self):
        self.grant_permission(self.request.user, 'Addons:Review')
        expected = ['reject_multiple_versions', 'reply', 'super', 'comment']
        f_statuses = [amo.STATUS_APPROVED, amo.STATUS_DISABLED]
        for file_status in f_statuses:
            assert list(self.get_review_actions(
                addon_status=amo.STATUS_APPROVED,
                file_status=file_status).keys()) == expected

    def test_actions_public_post_reviewer(self):
        self.grant_permission(self.request.user, 'Addons:PostReview')
        expected = ['reject_multiple_versions', 'reply', 'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED).keys()) == expected

        # Now make current version auto-approved...
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        expected = ['confirm_auto_approved', 'reject_multiple_versions',
                    'reply', 'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED).keys()) == expected

    def test_actions_content_review(self):
        self.grant_permission(self.request.user, 'Addons:ContentReview')
        expected = ['approve_content', 'reject_multiple_versions',
                    'reply', 'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED,
            content_review=True).keys()) == expected

    def test_actions_content_review_non_approved_addon(self):
        # Content reviewers can also see add-ons before they are approved for
        # the first time.
        self.grant_permission(self.request.user, 'Addons:ContentReview')
        expected = ['approve_content', 'reject_multiple_versions',
                    'reply', 'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW,
            content_review=True).keys()) == expected

    def test_actions_public_static_theme(self):
        # Having Addons:PostReview and dealing with a public add-on would
        # normally be enough to give you access to reject multiple versions
        # action, but it should not be available for static themes.
        self.grant_permission(self.request.user, 'Addons:PostReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        expected = []
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_AWAITING_REVIEW).keys()) == expected

        # Themes reviewers get access to everything.
        self.request.user.groupuser_set.all().delete()
        self.grant_permission(self.request.user, 'Addons:ThemeReview')
        expected = ['public', 'reject', 'reply', 'super', 'comment']
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_AWAITING_REVIEW).keys()) == expected

    def test_actions_no_version(self):
        """Deleted addons and addons with no versions in that channel have no
        version set."""
        expected = []
        self.version = None
        assert list(self.get_review_actions(
            addon_status=amo.STATUS_APPROVED,
            file_status=amo.STATUS_APPROVED).keys()) == expected

    def test_set_files(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.handler.set_files(amo.STATUS_APPROVED,
                                      self.version.files.all())

        self.file = self.version.files.all()[0]
        assert self.file.status == amo.STATUS_APPROVED
        assert self.file.datestatuschanged.date() > yesterday.date()

    def test_logs(self):
        self.helper.set_data({'comments': 'something'})
        self.helper.handler.log_action(amo.LOG.APPROVE_VERSION)
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_notify_email(self):
        self.helper.set_data(self.get_data())
        base_fragment = 'To respond, please reply to this email or visit'
        user = self.addon.listed_authors[0]
        ActivityLogToken.objects.create(version=self.version, user=user)
        uuid = self.version.token.get(user=user).uuid.hex
        reply_email = (
            'reviewreply+%s@%s' % (uuid, settings.INBOUND_EMAIL_DOMAIN))

        templates = (
            'extension_nominated_to_approved',
            'extension_nominated_to_rejected',
            'extension_pending_to_rejected',
            'theme_nominated_to_approved',
            'theme_nominated_to_rejected',
            'theme_pending_to_rejected',)
        for template in templates:
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            assert base_fragment in mail.outbox[0].body
            assert mail.outbox[0].reply_to == [reply_email]

        mail.outbox = []
        # This one does not inherit from base.txt because it's for unlisted
        # signing notification, which is not really something that necessitates
        # reviewer interaction, so it's simpler.
        template = 'unlisted_to_reviewed_auto'
        self.helper.handler.notify_email(template, 'Sample subject %s, %s')
        assert len(mail.outbox) == 1
        assert base_fragment not in mail.outbox[0].body
        assert mail.outbox[0].reply_to == [reply_email]

    def test_email_links(self):
        expected = {
            'extension_nominated_to_approved': 'addon_url',
            'extension_nominated_to_rejected': 'dev_versions_url',

            'extension_pending_to_approved': 'addon_url',
            'extension_pending_to_rejected': 'dev_versions_url',

            'theme_nominated_to_approved': 'addon_url',
            'theme_nominated_to_rejected': 'dev_versions_url',

            'theme_pending_to_approved': 'addon_url',
            'theme_pending_to_rejected': 'dev_versions_url',

            'unlisted_to_reviewed_auto': 'dev_versions_url',
        }

        self.helper.set_data(self.get_data())
        context_data = self.helper.handler.get_context_data()
        for template, context_key in expected.items():
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            assert context_key in context_data
            assert context_data.get(context_key) in mail.outbox[0].body

    def test_send_reviewer_reply(self):
        assert not self.addon.pending_info_request
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.reviewer_reply()

        assert not self.addon.pending_info_request

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == self.preamble

        assert self.check_log_count(amo.LOG.REVIEWER_REPLY_VERSION.id) == 1

    def test_request_more_information(self):
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.data['info_request'] = True
        self.helper.handler.reviewer_reply()

        self.assertCloseToNow(
            self.addon.pending_info_request,
            now=datetime.now() + timedelta(days=7))

        assert len(mail.outbox) == 1
        assert (
            mail.outbox[0].subject ==
            'Mozilla Add-ons: Action Required for Delicious Bookmarks 2.1.072')

        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 1

    def test_request_more_information_custom_deadline(self):
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.data['info_request'] = True
        self.helper.handler.data['info_request_deadline'] = 42
        self.helper.handler.reviewer_reply()

        self.assertCloseToNow(
            self.addon.pending_info_request,
            now=datetime.now() + timedelta(days=42))

        assert len(mail.outbox) == 1
        assert (
            mail.outbox[0].subject ==
            'Mozilla Add-ons: Action Required for Delicious Bookmarks 2.1.072')

        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 1

    def test_request_more_information_reset_notified_flag(self):
        self.setup_data(amo.STATUS_APPROVED)

        flags = AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=datetime.now() - timedelta(days=1),
            notified_about_expiring_info_request=True)

        self.helper.handler.data['info_request'] = True
        self.helper.handler.reviewer_reply()

        flags.reload()

        self.assertCloseToNow(
            flags.pending_info_request,
            now=datetime.now() + timedelta(days=7))
        assert not flags.notified_about_expiring_info_request

        assert len(mail.outbox) == 1
        assert (
            mail.outbox[0].subject ==
            'Mozilla Add-ons: Action Required for Delicious Bookmarks 2.1.072')

        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 1

    def test_request_more_information_deleted_addon(self):
        self.addon.delete()
        self.test_request_more_information()

    def test_email_no_locale(self):
        self.addon.name = {
            'es': '¿Dónde está la biblioteca?'
        }
        self.setup_data(amo.STATUS_NOMINATED)
        with translation.override('es'):
            assert translation.get_language() == 'es'
            self.helper.handler.process_public()

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            u'Mozilla Add-ons: Delicious Bookmarks 2.1.072 Approved')
        assert '/en-US/firefox/addon/a3615' not in mail.outbox[0].body
        assert '/es/firefox/addon/a3615' not in mail.outbox[0].body
        assert '/addon/a3615' in mail.outbox[0].body
        assert 'Your add-on, Delicious Bookmarks ' in mail.outbox[0].body

    def test_nomination_to_public_no_files(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_public()

        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

    def test_nomination_to_public_and_current_version(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(_current_version=None)
        assert not self.addon.current_version

        self.helper.handler.process_public()
        self.addon = Addon.objects.get(pk=3615)
        assert self.addon.current_version

    def test_nomination_to_public_new_addon(self):
        """ Make sure new add-ons can be made public (bug 637959) """
        status = amo.STATUS_NOMINATED
        self.setup_data(status)

        # Make sure we have no public files
        for version in self.addon.versions.all():
            version.files.update(status=amo.STATUS_AWAITING_REVIEW)

        self.helper.handler.process_public()

        # Re-fetch the add-on
        addon = Addon.objects.get(pk=3615)

        assert addon.status == amo.STATUS_APPROVED

        assert addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == '%s Approved' % self.preamble

        # AddonApprovalsCounter counter is now at 1 for this addon since there
        # was a human review.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1
        self.assertCloseToNow(approval_counter.last_human_review)

        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_FULL)

    def test_nomination_to_public_need_human_review(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.version.update(needs_human_review=True)
        self.helper.handler.process_public()
        self.addon.reload()
        self.version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert not self.version.needs_human_review

    def test_nomination_to_public_need_human_review_no_request(self):
        self.request = None
        self.setup_data(amo.STATUS_NOMINATED)
        self.version.update(needs_human_review=True)
        self.helper.handler.process_public()
        self.addon.reload()
        self.version.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.version.needs_human_review

    @patch('olympia.reviewers.utils.sign_file')
    def test_nomination_to_public(self, sign_mock):
        sign_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)

        self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s Approved' % self.preamble)
        assert 'has been approved' in mail.outbox[0].body

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        sign_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('olympia.reviewers.utils.sign_file')
    def test_old_nomination_to_public_bonus_score(self, sign_mock):
        sign_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)
        self.version.update(nomination=self.days_ago(9))

        self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s Approved' % self.preamble)
        assert 'has been approved' in mail.outbox[0].body

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        sign_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        # Score has bonus points added for reviewing an old add-on.
        # 2 days over the limit = 4 points
        self._check_score(amo.REVIEWED_ADDON_FULL, bonus=4)

    @patch('olympia.reviewers.utils.sign_file')
    def test_nomination_to_public_no_request(self, sign_mock):
        self.request = None
        sign_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)

        self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s Approved' % self.preamble)
        assert 'has been approved' in mail.outbox[0].body

        # AddonApprovalsCounter counter is now at 0 for this addon since there
        # was an automatic approval.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 0
        # Since approval counter did not exist for this add-on before, the last
        # human review field should be empty.
        assert approval_counter.last_human_review is None

        sign_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        # No request, no user, therefore no score.
        assert ReviewerScore.objects.count() == 0

    @patch('olympia.reviewers.utils.sign_file')
    def test_public_addon_with_version_awaiting_review_to_public(
            self, sign_mock):
        sign_mock.reset()
        self.addon.current_version.update(created=self.days_ago(1))
        self.version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.preamble = 'Mozilla Add-ons: Delicious Bookmarks 3.0.42'
        self.file = self.version.files.all()[0]
        self.setup_data(amo.STATUS_APPROVED)
        self.create_paths()
        AddonApprovalsCounter.objects.create(
            addon=self.addon, counter=1, last_human_review=self.days_ago(42))

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        self.helper.handler.process_public()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s Updated' % self.preamble)
        assert 'has been updated' in mail.outbox[0].body

        # AddonApprovalsCounter counter is now at 2 for this addon since there
        # was another human review. The last human review date should have been
        # updated.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 2
        self.assertCloseToNow(approval_counter.last_human_review)

        sign_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_UPDATE)

    @patch('olympia.reviewers.utils.sign_file')
    def test_public_addon_with_version_need_human_review_to_public(
            self, sign_file_mock):
        self.old_version = self.addon.current_version
        self.old_version.update(
            created=self.days_ago(1),
            needs_human_review=True)
        self.version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.file = self.version.files.all()[0]
        self.setup_data(amo.STATUS_APPROVED)

        self.helper.handler.process_public()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)
        self.old_version.reload()
        assert not self.old_version.needs_human_review

    @patch('olympia.reviewers.utils.sign_file')
    def test_public_addon_with_version_awaiting_review_to_sandbox(
            self, sign_mock):
        sign_mock.reset()
        self.addon.current_version.update(created=self.days_ago(1))
        self.version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.preamble = 'Mozilla Add-ons: Delicious Bookmarks 3.0.42'
        self.file = self.version.files.all()[0]
        self.setup_data(amo.STATUS_APPROVED)
        self.create_paths()
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        self.helper.handler.process_sandbox()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_DISABLED
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            "%s didn't pass review" % self.preamble)
        assert 'reviewed and did not meet the criteria' in mail.outbox[0].body

        # AddonApprovalsCounter counter is still at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        assert not sign_mock.called
        assert storage.exists(self.file.guarded_file_path)
        assert not storage.exists(self.file.file_path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_UPDATE)

    def test_public_addon_with_version_need_human_review_to_sandbox(self):
        self.old_version = self.addon.current_version
        self.old_version.update(
            created=self.days_ago(1),
            needs_human_review=True)
        self.version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            version='3.0.42',
            needs_human_review=True,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.file = self.version.files.all()[0]
        self.setup_data(amo.STATUS_APPROVED)

        self.helper.handler.process_sandbox()

        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_DISABLED
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        # Both version awaiting review and current public version had been
        # flagged as needing human review. Only the newer version has been
        # reviewed and rejected, so we leave the flag on past versions (unlike
        # approvals, we can't be sure the current version is safe now).
        self.addon.current_version.reload()
        assert self.addon.current_version.needs_human_review

        self.version.reload()
        assert not self.version.needs_human_review

    def test_public_addon_confirm_auto_approval(self):
        self.grant_permission(self.request.user, 'Addons:PostReview')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=151)
        assert summary.confirmed is None
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        self.helper.handler.confirm_auto_approved()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (ActivityLog.objects.for_addons(self.addon)
                               .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
                               .get())
        assert activity.arguments == [self.addon, self.version]
        assert activity.details['comments'] == ''

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_public_with_unreviewed_version_addon_confirm_auto_approval(self):
        self.grant_permission(self.request.user, 'Addons:PostReview')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.current_version = self.version
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=152)
        self.version = version_factory(
            addon=self.addon, version='3.0',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.file = self.version.files.all()[0]
        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # Confirm approval action should be available even if the latest
        # version is not public, what we care about is the current_version.
        assert 'confirm_auto_approved' in self.helper.actions

        self.helper.handler.confirm_auto_approved()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (ActivityLog.objects.for_addons(self.addon)
                               .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
                               .get())
        assert activity.arguments == [self.addon, self.current_version]
        assert activity.details['comments'] == ''

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_public_with_disabled_version_addon_confirm_auto_approval(self):
        self.grant_permission(self.request.user, 'Addons:PostReview')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        self.current_version = self.version
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=153)
        self.version = version_factory(
            addon=self.addon, version='3.0',
            file_kw={'status': amo.STATUS_DISABLED})
        self.file = self.version.files.all()[0]
        self.helper = self.get_helper()  # To make it pick up the new version.
        self.helper.set_data(self.get_data())

        # Confirm approval action should be available even if the latest
        # version is not public, what we care about is the current_version.
        assert 'confirm_auto_approved' in self.helper.actions

        self.helper.handler.confirm_auto_approved()

        summary.reload()
        assert summary.confirmed is True
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        self.assertCloseToNow(approvals_counter.last_human_review)
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 0
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 1
        activity = (ActivityLog.objects.for_addons(self.addon)
                               .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
                               .get())
        assert activity.arguments == [self.addon, self.current_version]
        assert activity.details['comments'] == ''

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_addon_with_version_need_human_review_confirm_auto_approval(self):
        self.addon.current_version.update(needs_human_review=True)
        self.test_public_addon_confirm_auto_approval()
        self.addon.current_version.reload()
        assert self.addon.current_version.needs_human_review is False

    def test_unlisted_version_addon_confirm_multiple_versions(self):
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # This add-on will have 4 versions:
        # - one listed (the initial one from setup)
        # - one unlisted we'll confirm approval of (has an AutoApprovalSummary)
        # - one unlisted we'll confirm approval of (no AutoApprovalSummary) and
        #   flagged by scanners
        # - one unlisted flagged by scanners we'll leave alone
        first_unlisted = version_factory(
            addon=self.addon, version='3.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'is_webextension': True},
            created=self.days_ago(7))
        summary = AutoApprovalSummary.objects.create(
            version=first_unlisted, verdict=amo.AUTO_APPROVED)
        second_unlisted = version_factory(
            addon=self.addon, version='4.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'is_webextension': True},
            needs_human_review=True,
            created=self.days_ago(6))
        self.version = version_factory(
            addon=self.addon, version='5.0',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            needs_human_review=True,
            file_kw={'is_webextension': True},
            created=self.days_ago(5))
        self.file = self.version.files.all()[0]
        self.helper = self.get_helper()  # To make it pick up the new version.
        data = self.get_data().copy()
        data['versions'] = self.addon.versions.filter(
            pk__in=(first_unlisted.pk, second_unlisted.pk))
        self.helper.set_data(data)

        # Confirm multiple versions action should be available since we're
        # looking at an unlisted version and the reviewer has permission.
        assert 'confirm_multiple_versions' in self.helper.actions

        self.helper.handler.confirm_multiple_versions()

        summary.reload()
        assert summary.confirmed is True

        self.version.reload()
        assert self.version.needs_human_review  # Untouched.

        second_unlisted.reload()
        assert not second_unlisted.needs_human_review  # Cleared.

        assert (
            AddonApprovalsCounter.objects.filter(addon=self.addon).count() ==
            0)  # Not incremented since it was unlisted.

        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 2
        activities = (
            ActivityLog.objects.for_addons(self.addon)
                               .filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id)
                               .order_by('-pk')
        )
        activity = activities[0]
        assert activity.arguments == [self.addon, first_unlisted]
        activity = activities[1]
        assert activity.arguments == [self.addon, second_unlisted]

    @patch('olympia.reviewers.utils.sign_file')
    def test_null_to_public_unlisted(self, sign_mock):
        sign_mock.reset()
        self.setup_data(amo.STATUS_NULL,
                        channel=amo.RELEASE_CHANNEL_UNLISTED)

        self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        # AddonApprovalsCounter was not touched since the version we made
        # public is unlisted.
        assert not AddonApprovalsCounter.objects.filter(
            addon=self.addon).exists()

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s signed and ready to download' % self.preamble)
        assert ('%s is now signed and ready for you to download' %
                self.version.version in mail.outbox[0].body)
        assert 'You received this email because' not in mail.outbox[0].body

        sign_mock.assert_called_with(self.file)
        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    @patch('olympia.reviewers.utils.sign_file')
    def test_nomination_to_public_failed_signing(self, sign_mock):
        sign_mock.side_effect = Exception
        sign_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)

        with self.assertRaises(Exception):
            self.helper.handler.process_public()

        # AddonApprovalsCounter was not touched since we failed signing.
        assert not AddonApprovalsCounter.objects.filter(
            addon=self.addon).exists()

        # Status unchanged.
        assert self.addon.status == amo.STATUS_NOMINATED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_AWAITING_REVIEW)

        assert len(mail.outbox) == 0
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 0

    @patch('olympia.reviewers.utils.sign_file')
    def test_nomination_to_sandbox(self, sign_mock):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_sandbox()

        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_DISABLED)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s didn\'t pass review' % self.preamble)
        assert 'did not meet the criteria' in mail.outbox[0].body

        # AddonApprovalsCounter was not touched since we didn't approve.
        assert not AddonApprovalsCounter.objects.filter(
            addon=self.addon).exists()

        assert not sign_mock.called
        assert storage.exists(self.file.guarded_file_path)
        assert not storage.exists(self.file.file_path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_email_unicode_monster(self):
        self.addon.name = u'TaobaoShopping淘宝网导航按钮'
        self.addon.save()
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_sandbox()
        assert u'TaobaoShopping淘宝网导航按钮' in mail.outbox[0].subject

    def test_nomination_to_super_review(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_code_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CODE.id) == 1

    def test_auto_approved_admin_code_review(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_code_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CODE.id) == 1

    def test_auto_approved_admin_content_review(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED,
                        content_review=True)
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_content_review
        assert self.check_log_count(
            amo.LOG.REQUEST_ADMIN_REVIEW_CONTENT.id) == 1

    def test_auto_approved_admin_theme_review(self):
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED,
                        type=amo.ADDON_STATICTHEME)
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_theme_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_THEME.id) == 1

    def test_nomination_to_super_review_and_escalate(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.helper.handler.process_super_review()

        assert self.addon.needs_admin_code_review
        assert self.check_log_count(amo.LOG.REQUEST_ADMIN_REVIEW_CODE.id) == 1

    def test_operating_system_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        self.helper.handler.process_sandbox()

        assert 'Tested on osx with Firefox' in mail.outbox[0].body

    def test_operating_system_not_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        data = self.get_data().copy()
        data['operating_systems'] = ''
        self.helper.set_data(data)
        self.helper.handler.process_sandbox()

        assert 'Tested with Firefox' in mail.outbox[0].body

    def test_application_not_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        data = self.get_data().copy()
        data['applications'] = ''
        self.helper.set_data(data)
        self.helper.handler.process_sandbox()

        assert 'Tested on osx' in mail.outbox[0].body

    def test_both_not_present(self):
        self.setup_data(amo.STATUS_APPROVED)
        data = self.get_data().copy()
        data['applications'] = ''
        data['operating_systems'] = ''
        self.helper.set_data(data)
        self.helper.handler.process_sandbox()

        assert 'Tested' not in mail.outbox[0].body

    def test_pending_to_super_review(self):
        for status in (amo.STATUS_DISABLED, amo.STATUS_NULL):
            self.setup_data(status)
            self.helper.handler.process_super_review()

            assert self.addon.needs_admin_code_review

    def test_nominated_review_time_set_version_process_public(self):
        self.version.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_public()
        assert self.version.reload().reviewed

    def test_nominated_review_time_set_version_process_sandbox(self):
        self.version.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_sandbox()
        assert self.version.reload().reviewed

    def test_nominated_review_time_set_file_process_public(self):
        self.file.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_public()
        assert File.objects.get(pk=self.file.pk).reviewed

    def test_nominated_review_time_set_file_process_sandbox(self):
        self.file.update(reviewed=None)
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_sandbox()
        assert File.objects.get(pk=self.file.pk).reviewed

    def test_review_unlisted_while_a_listed_version_is_awaiting_review(self):
        self.make_addon_unlisted(self.addon)
        self.version.reload()
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.get_helper()

    def test_reject_multiple_versions(self):
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=101)
        # An extra file should not change anything.
        file_factory(version=self.version, platform=amo.PLATFORM_LINUX.id)
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.addon.authors.all()[0].email]
        assert mail.outbox[0].subject == (
            u'Mozilla Add-ons: Delicious Bookmarks has been disabled on '
            u'addons.mozilla.org')
        assert ('your add-on Delicious Bookmarks has been disabled'
                in mail.outbox[0].body)
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in mail.outbox[0].reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        logs = (ActivityLog.objects.for_addons(self.addon)
                                   .filter(action=amo.LOG.REJECT_VERSION.id))
        assert logs[0].created == logs[1].created

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_reject_multiple_versions_except_latest(self):
        old_version = self.version
        extra_version = version_factory(addon=self.addon, version='3.1')
        # Add yet another version we don't want to reject.
        self.version = version_factory(addon=self.addon, version='42.0')
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED, weight=91)
        self.setup_data(amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all().exclude(
            pk=self.version.pk)
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        # latest_version is still public so the add-on is still public.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.current_version == self.version
        assert list(self.addon.versions.all().order_by('-pk')) == [
            self.version, extra_version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.addon.authors.all()[0].email]
        assert mail.outbox[0].subject == (
            u'Mozilla Add-ons: Versions disabled for Delicious Bookmarks')
        assert ('Version(s) affected and disabled:\n3.1, 2.1.072'
                in mail.outbox[0].body)
        log_token = ActivityLogToken.objects.filter(
            version=self.version).get()
        assert log_token.uuid.hex in mail.outbox[0].reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0

        # Check points awarded.
        self._check_score(amo.REVIEWED_EXTENSION_MEDIUM_RISK)

    def test_reject_multiple_versions_need_human_review(self):
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(
            addon=self.addon, version='3.0', needs_human_review=True)

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.version, old_version]
        # We rejected all versions so there aren't any left that need human
        # review.
        assert not self.addon.versions.filter(needs_human_review=True).exists()
        assert self.file.status == amo.STATUS_DISABLED

    def test_reject_multiple_versions_content_review(self):
        self.grant_permission(self.request.user, 'Addons:ContentReview')
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED,
            content_review=True)

        # Safeguards.
        assert isinstance(self.helper.handler, ReviewFiles)
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.is_public()

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.version, old_version]
        assert self.file.status == amo.STATUS_DISABLED

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [self.addon.authors.all()[0].email]
        assert mail.outbox[0].subject == (
            u'Mozilla Add-ons: Delicious Bookmarks has been disabled on '
            u'addons.mozilla.org')
        assert ('your add-on Delicious Bookmarks has been disabled'
                in mail.outbox[0].body)
        log_token = ActivityLogToken.objects.get()
        assert log_token.uuid.hex in mail.outbox[0].reply_to[0]

        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 0
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 2

    def test_approve_content_content_review(self):
        self.grant_permission(self.request.user, 'Addons:ContentReview')
        self.setup_data(
            amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED,
            content_review=True)
        summary = AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED)
        self.create_paths()

        # Safeguards.
        assert self.addon.status == amo.STATUS_APPROVED
        assert self.file.status == amo.STATUS_APPROVED
        assert self.addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

        self.helper.handler.approve_content()

        summary.reload()
        assert summary.confirmed is None  # unchanged.
        approvals_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approvals_counter.counter == 0
        assert approvals_counter.last_human_review is None
        self.assertCloseToNow(approvals_counter.last_content_review)
        assert self.check_log_count(amo.LOG.CONFIRM_AUTO_APPROVED.id) == 0
        assert self.check_log_count(amo.LOG.APPROVE_CONTENT.id) == 1
        activity = (ActivityLog.objects.for_addons(self.addon)
                               .filter(action=amo.LOG.APPROVE_CONTENT.id)
                               .get())
        assert activity.arguments == [self.addon, self.version]
        assert activity.details['comments'] == ''

        # Check points awarded.
        self._check_score(amo.REVIEWED_CONTENT_REVIEW)

    def test_dev_versions_url_in_context(self):
        self.helper.set_data(self.get_data())
        context_data = self.helper.handler.get_context_data()
        assert context_data['dev_versions_url'] == absolutify(
            self.addon.get_dev_url('versions'))

        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        context_data = self.helper.handler.get_context_data()
        assert context_data['dev_versions_url'] == absolutify(
            reverse('devhub.addons.versions', args=[self.addon.id]))

    def test_nominated_to_approved_recommended(self):
        DiscoveryItem.objects.create(
            addon=self.addon, recommendable=True)
        assert not self.addon.is_recommended
        self.test_nomination_to_public()
        del self.addon.is_recommended
        assert self.addon.current_version.recommendation_approved is True
        assert self.addon.is_recommended

    def test_approved_update_recommended(self):
        DiscoveryItem.objects.create(
            addon=self.addon, recommendable=True)
        assert not self.addon.is_recommended
        self.test_public_addon_with_version_awaiting_review_to_public()
        del self.addon.is_recommended
        assert self.addon.current_version.recommendation_approved is True
        assert self.addon.is_recommended is True

    def test_autoapprove_fails_for_recommended(self):
        DiscoveryItem.objects.create(
            addon=self.addon, recommendable=True)
        assert not self.addon.is_recommended
        self.request.user = UserProfile.objects.get(id=settings.TASK_USER_ID)
        with self.assertRaises(AssertionError):
            self.test_nomination_to_public()
        assert self.addon.current_version.recommendation_approved is False
        assert not self.addon.is_recommended

    def _test_block_multiple_unlisted_versions(self, redirect_url):
        old_version = self.version
        self.version = version_factory(addon=self.addon, version='3.0')
        # An extra file should not change anything.
        file_factory(version=self.version, platform=amo.PLATFORM_LINUX.id)
        self.setup_data(
            amo.STATUS_NULL, file_status=amo.STATUS_APPROVED,
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        # Safeguards.
        assert isinstance(self.helper.handler, ReviewUnlisted)
        assert self.addon.status == amo.STATUS_NULL
        assert self.file.status == amo.STATUS_APPROVED

        data = self.get_data().copy()
        data['versions'] = self.addon.versions.all()
        self.helper.set_data(data)
        self.helper.handler.reject_multiple_versions()

        self.addon.reload()
        self.file.reload()
        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.current_version is None
        assert list(self.addon.versions.all()) == [self.version, old_version]
        assert self.file.status == amo.STATUS_DISABLED
        # We rejected all versions so there aren't any left that need human
        # review.
        assert not self.addon.versions.filter(needs_human_review=True).exists()

        # No mails
        assert len(mail.outbox) == 0

        # Normal logs though
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 2
        assert self.check_log_count(amo.LOG.REJECT_CONTENT.id) == 0
        logs = (ActivityLog.objects.for_addons(self.addon)
                                   .filter(action=amo.LOG.REJECT_VERSION.id))
        assert logs[0].created == logs[1].created

        # We should have set redirect_url to point to the Block admin page
        if '%s' in redirect_url:
            redirect_url = redirect_url % (
                old_version.version, self.version.version)
        assert self.helper.redirect_url == redirect_url

    def test_pending_blsubmission_multiple_unlisted_versions(self):
        subm = BLSubmission.objects.create(
            input_guids=self.addon.guid, updated_by=user_factory())
        redirect_url = (
            reverse('admin:blocklist_blsubmission_change', args=(subm.id,)))
        assert Block.objects.count() == 0
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_new_block_multiple_unlisted_versions(self):
        redirect_url = (
            reverse('admin:blocklist_blsubmission_add') +
            '?min_version=%s&max_version=%s&guids=' + self.addon.guid)
        assert Block.objects.count() == 0
        self._test_block_multiple_unlisted_versions(redirect_url)

    def test_existing_block_multiple_unlisted_versions(self):
        block = Block.objects.create(
            guid=self.addon.guid, updated_by=user_factory())
        redirect_url = (
            reverse('admin:blocklist_block_change', args=(block.id,)) +
            '?min_version=%s&max_version=%s')
        self._test_block_multiple_unlisted_versions(redirect_url)


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestReviewHelperSigning(TestReviewHelperBase):
    """Tests that call signing but don't mock the actual call.

    Instead tests will have to check the end-result to see if the signing
    calls succeeded.
    """
    __test__ = True

    def setUp(self):
        super().setUp()
        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

        self.addon = addon_factory(
            guid='test@local', file_kw={'filename': 'webextension.xpi'},
            users=[self.request.user])
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.files.all()[0]

    def test_nomination_to_public(self):
        self.setup_data(amo.STATUS_NOMINATED)

        self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        assert len(mail.outbox) == 1

        # AddonApprovalsCounter counter is now at 1 for this addon.
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1

        assert storage.exists(self.file.file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        signature_info, manifest = _get_signature_details(self.file.file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'test@local'
        assert manifest.count('Name: ') == 4

        assert 'Name: index.js' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest

    def test_nominated_to_public_recommended(self):
        self.setup_data(amo.STATUS_NOMINATED)

        DiscoveryItem.objects.create(
            addon=self.addon, recommendable=True)
        assert not self.addon.is_recommended

        self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_APPROVED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_APPROVED)

        del self.addon.is_recommended
        assert self.addon.current_version.recommendation_approved is True
        assert self.addon.is_recommended

        signature_info, manifest = _get_signature_details(self.file.file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'test@local'
        assert manifest.count('Name: ') == 5

        assert 'Name: index.js' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest
        assert 'Name: mozilla-recommendation.json' in manifest

        recommendation_data = _get_recommendation_data(self.file.file_path)
        assert recommendation_data['addon_id'] == 'test@local'
        assert recommendation_data['states'] == ['recommended']


def test_send_email_autoescape():
    s = 'woo&&<>\'""'

    # Make sure HTML is not auto-escaped.
    send_mail(u'Random subject with %s', s,
              recipient_list=['nobody@mozilla.org'],
              from_email='nobody@mozilla.org',
              use_deny_list=False)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].body == s
