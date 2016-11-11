# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.utils import translation

import pytest
from mock import Mock, patch
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLogToken
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse
from olympia.devhub.models import ActivityLog
from olympia.editors import helpers
from olympia.editors.models import ReviewerScore
from olympia.files.models import File
from olympia.translations.models import Translation
from olympia.users.models import UserProfile
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


REVIEW_FILES_STATUSES = (amo.STATUS_PUBLIC, amo.STATUS_DISABLED)


class TestViewPendingQueueTable(TestCase):

    def setUp(self):
        super(TestViewPendingQueueTable, self).setUp()
        self.table = helpers.ViewPendingQueueTable([])

    def test_addon_name(self):
        row = Mock()
        page = Mock()
        page.start_index = Mock()
        page.start_index.return_value = 1
        row.addon_name = 'フォクすけといっしょ'.decode('utf8')
        row.addon_slug = 'test'
        row.latest_version = u'0.12'
        self.table.set_page(page)
        a = pq(self.table.render_addon_name(row))

        assert a.attr('href') == (
            reverse('editors.review', args=[str(row.addon_slug)]))
        assert a.text() == "フォクすけといっしょ 0.12".decode('utf8')

    def test_addon_type_id(self):
        row = Mock()
        row.addon_type_id = amo.ADDON_THEME
        assert unicode(self.table.render_addon_type_id(row)) == (
            u'Complete Theme')

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
        self.table = helpers.ViewUnlistedAllListTable([])

    def test_addon_name(self):
        row = Mock()
        page = Mock()
        page.start_index = Mock()
        page.start_index.return_value = 1
        row.addon_name = 'フォクすけといっしょ'.decode('utf8')
        row.addon_slug = 'test'
        row.latest_version = u'0.12'
        self.table.set_page(page)
        a = pq(self.table.render_addon_name(row))

        assert (a.attr('href') == reverse('editors.review',
                                          args=[str(row.addon_slug)]))
        assert a.text() == 'フォクすけといっしょ 0.12'.decode('utf8')

    def test_last_review(self):
        row = Mock()
        row.review_version_num = u'0.34.3b'
        row.review_date = u'2016-01-01'
        doc = pq(self.table.render_review_date(row))
        assert doc.text() == u'0.34.3b on 2016-01-01'

    def test_no_review(self):
        row = Mock()
        row.review_version_num = None
        row.review_date = None
        doc = pq(self.table.render_review_date(row))
        assert doc.text() == u'No Reviews'

    def test_authors_few(self):
        row = Mock()
        row.authors = [(123, 'bob'), (456, 'steve')]
        doc = pq(self.table.render_authors(row))
        assert doc('span').text() == 'bob steve'
        assert doc('span a:eq(0)').attr('href') == UserProfile.create_user_url(
            123, username='bob')
        assert doc('span a:eq(1)').attr('href') == UserProfile.create_user_url(
            456, username='steve')
        assert doc('span').attr('title') == 'bob steve'

    def test_authors_four(self):
        row = Mock()
        row.authors = [(123, 'bob'), (456, 'steve'), (789, 'cvan'),
                       (999, 'basta')]
        doc = pq(self.table.render_authors(row))
        assert doc.text() == 'bob steve cvan ...'
        assert doc('span a:eq(0)').attr('href') == UserProfile.create_user_url(
            123, username='bob')
        assert doc('span a:eq(1)').attr('href') == UserProfile.create_user_url(
            456, username='steve')
        assert doc('span a:eq(2)').attr('href') == UserProfile.create_user_url(
            789, username='cvan')
        assert doc('span').attr('title') == 'bob steve cvan basta', doc.html()


yesterday = datetime.today() - timedelta(days=1)


class TestReviewHelper(TestCase):
    fixtures = ['base/addon_3615', 'base/users']
    preamble = 'Mozilla Add-ons: Delicious Bookmarks 2.1.072'

    def setUp(self):
        super(TestReviewHelper, self).setUp()

        class FakeRequest:
            user = UserProfile.objects.get(pk=10482)

        self.request = FakeRequest()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.files.all()[0]

        self.create_paths()

    def _check_score(self, reviewed_type):
        scores = ReviewerScore.objects.all()
        assert len(scores) > 0
        assert scores[0].score == amo.REVIEWED_SCORES[reviewed_type]
        assert scores[0].note_key == reviewed_type

    def create_paths(self):
        if not storage.exists(self.file.file_path):
            with storage.open(self.file.file_path, 'w') as f:
                f.write('test data\n')

    def get_data(self):
        return {'comments': 'foo', 'addon_files': self.version.files.all(),
                'action': 'public', 'operating_systems': 'osx',
                'applications': 'Firefox'}

    def get_helper(self):
        return helpers.ReviewHelper(request=self.request, addon=self.addon,
                                    version=self.version)

    def setup_type(self, status):
        self.addon.update(status=status)
        return self.get_helper().handler.review_type

    def check_log_count(self, id):
        return (ActivityLog.objects.for_addons(self.helper.addon)
                                   .filter(action=id).count())

    def test_no_request(self):
        self.request = None
        helper = self.get_helper()
        assert helper.actions == {}

    def test_type_nominated(self):
        assert self.setup_type(amo.STATUS_NOMINATED) == 'nominated'

    def test_type_pending(self):
        assert self.setup_type(amo.STATUS_PENDING) == 'pending'
        assert self.setup_type(amo.STATUS_NULL) == 'pending'
        assert self.setup_type(amo.STATUS_PUBLIC) == 'pending'
        assert self.setup_type(amo.STATUS_DISABLED) == 'pending'
        assert self.setup_type(amo.STATUS_BETA) == 'pending'

    def test_no_version(self):
        helper = helpers.ReviewHelper(request=self.request, addon=self.addon,
                                      version=None)
        assert helper.handler.review_type == 'pending'

    def test_review_files(self):
        for status in REVIEW_FILES_STATUSES:
            self.setup_data(status=status)
            assert self.helper.handler.__class__ == helpers.ReviewFiles

    def test_review_addon(self):
        self.setup_data(status=amo.STATUS_NOMINATED)
        assert self.helper.handler.__class__ == helpers.ReviewAddon

    def test_process_action_none(self):
        self.helper.set_data({'action': 'foo'})
        self.assertRaises(self.helper.process)

    def test_process_action_good(self):
        self.helper.set_data({'action': 'info', 'comments': 'foo'})
        self.helper.process()
        assert len(mail.outbox) == 1

    def test_clear_has_info_request(self):
        self.version.update(has_info_request=True)
        assert self.version.has_info_request
        self.helper.set_data({'action': 'comment', 'comments': 'foo',
                              'clear_info_request': True})
        self.helper.process()
        assert not self.version.has_info_request

    def test_do_not_clear_has_info_request(self):
        self.version.update(has_info_request=True)
        assert self.version.has_info_request
        self.helper.set_data({'action': 'comment', 'comments': 'foo'})
        self.helper.process()
        assert self.version.has_info_request

    def test_action_details(self):
        for status in Addon.STATUS_CHOICES:
            self.addon.update(status=status)
            helper = self.get_helper()
            actions = helper.actions
            for k, v in actions.items():
                assert unicode(v['details']), "Missing details for: %s" % k

    def get_review_actions(self, addon_status, file_status):
        self.file.update(status=file_status)
        self.addon.update(status=addon_status)
        return self.get_helper().actions

    def test_actions_full_nominated(self):
        expected = ['public', 'reject', 'info', 'super', 'comment']
        assert self.get_review_actions(
            addon_status=amo.STATUS_NOMINATED,
            file_status=amo.STATUS_AWAITING_REVIEW).keys() == expected

    def test_actions_full_update(self):
        expected = ['public', 'reject', 'info', 'super', 'comment']
        assert self.get_review_actions(
            addon_status=amo.STATUS_PUBLIC,
            file_status=amo.STATUS_AWAITING_REVIEW).keys() == expected

    def test_actions_full_nonpending(self):
        expected = ['info', 'super', 'comment']
        f_statuses = [amo.STATUS_PUBLIC, amo.STATUS_DISABLED]
        for file_status in f_statuses:
            assert self.get_review_actions(
                addon_status=amo.STATUS_PUBLIC,
                file_status=file_status).keys() == expected

    def test_set_files(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.set_data({'addon_files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['addon_files'])

        self.file = self.version.files.all()[0]
        assert self.file.status == amo.STATUS_PUBLIC
        assert self.file.datestatuschanged.date() > yesterday.date()

    def test_set_files_copy(self):
        self.helper.set_data({'addon_files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['addon_files'],
                                      copy_to_mirror=True)

        assert storage.exists(self.file.mirror_file_path)

    def test_set_files_remove(self):
        with storage.open(self.file.mirror_file_path, 'wb') as f:
            f.write('test data\n')
        self.helper.set_data({'addon_files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['addon_files'],
                                      hide_disabled_file=True)

        assert not storage.exists(self.file.mirror_file_path)

    def test_logs(self):
        self.helper.set_data({'comments': 'something'})
        self.helper.handler.log_action(amo.LOG.APPROVE_VERSION)
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    def test_notify_email(self):
        self.helper.set_data(self.get_data())
        base_fragment = 'reply to this email or join #amo-editors'
        for template in ('nominated_to_nominated',
                         'nominated_to_public', 'nominated_to_sandbox',
                         'pending_to_public', 'pending_to_sandbox',
                         'author_super_review', 'unlisted_to_reviewed_auto'):
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            assert base_fragment in mail.outbox[0].body

    @override_switch('activity-email', active=True)
    def test_notify_email_activity_email(self):
        self.helper.set_data(self.get_data())
        base_fragment = 'If you need to send file attachments'
        user = self.addon.listed_authors[0]
        ActivityLogToken.objects.create(version=self.version, user=user)
        uuid = self.version.token.get(user=user).uuid.hex
        reply_email = (
            'reviewreply+%s@%s' % (uuid, settings.INBOUND_EMAIL_DOMAIN))

        for template in ('nominated_to_nominated', 'nominated_to_public',
                         'nominated_to_sandbox', 'pending_to_public',
                         'pending_to_sandbox', 'author_super_review',
                         'unlisted_to_reviewed_auto'):
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            assert base_fragment in mail.outbox[0].body
            assert mail.outbox[0].reply_to == [reply_email]

    def test_email_links(self):
        expected = {
            'nominated_to_nominated': 'addon_url',
            'nominated_to_public': 'addon_url',
            'nominated_to_sandbox': 'dev_versions_url',

            'pending_to_public': 'addon_url',
            'pending_to_sandbox': 'dev_versions_url',

            'unlisted_to_reviewed_auto': 'dev_versions_url',
        }

        self.helper.set_data(self.get_data())
        context_data = self.helper.handler.get_context_data()
        for template, context_key in expected.iteritems():
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            assert context_key in context_data
            assert context_data.get(context_key) in mail.outbox[0].body

    def setup_data(self, status, delete=None,
                   channel=amo.RELEASE_CHANNEL_LISTED):
        if delete is None:
            delete = []
        mail.outbox = []
        ActivityLog.objects.for_addons(self.helper.addon).delete()
        self.addon.update(status=status,
                          is_listed=channel == amo.RELEASE_CHANNEL_LISTED)
        self.version.update(channel=channel)
        file_status = (
            amo.STATUS_AWAITING_REVIEW if status == amo.STATUS_NOMINATED
            else status)
        self.file.update(status=file_status)
        self.helper = self.get_helper()
        data = self.get_data().copy()
        for key in delete:
            del data[key]
        self.helper.set_data(data)

    def test_request_more_information(self):
        self.setup_data(amo.STATUS_PUBLIC, ['addon_files'])
        self.helper.handler.request_information()

        assert self.version.has_info_request

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == self.preamble

        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 1

    def test_request_more_information_no_versions(self):
        assert len(mail.outbox) == 0
        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 0
        self.version.delete()
        self.helper = helpers.ReviewHelper(request=self.request,
                                           addon=self.addon)
        data = {'comments': 'foo', 'action': 'info',
                'operating_systems': 'osx', 'applications': 'Firefox'}
        self.helper.set_data(data)
        self.helper.handler.request_information()

        assert len(mail.outbox) == 1
        subject = 'Mozilla Add-ons: Delicious Bookmarks '
        assert mail.outbox[0].subject == subject
        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 1

    def test_request_more_information_deleted_addon(self):
        self.addon.delete()
        self.test_request_more_information()

    def test_email_no_locale(self):
        self.addon.name = {
            'es': '¿Dónde está la biblioteca?'
        }
        self.setup_data(amo.STATUS_NOMINATED, ['addon_files'])
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
        self.setup_data(amo.STATUS_NOMINATED, ['addon_files'])
        self.helper.handler.process_public()

        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_PUBLIC)

    def test_nomination_to_public_and_current_version(self):
        self.setup_data(amo.STATUS_NOMINATED, ['addon_files'])
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
        for i in self.addon.versions.all():
            i.files.update(status=amo.STATUS_AWAITING_REVIEW)

        self.helper.handler.process_public()

        # Re-fetch the add-on
        addon = Addon.objects.get(pk=3615)

        assert addon.status == amo.STATUS_PUBLIC

        assert addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_PUBLIC)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == '%s Approved' % self.preamble

        assert storage.exists(self.file.mirror_file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('olympia.editors.helpers.sign_file')
    def test_nomination_to_public(self, sign_mock):
        sign_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)
        with self.settings(SIGNING_SERVER='full'):
            self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_PUBLIC
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_PUBLIC)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s Approved' % self.preamble)
        assert 'has been approved' in mail.outbox[0].body

        sign_mock.assert_called_with(self.file, 'full')
        assert storage.exists(self.file.mirror_file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('olympia.editors.helpers.sign_file')
    def test_null_to_public_unlisted(self, sign_mock):
        sign_mock.reset()
        self.setup_data(amo.STATUS_NULL,
                        channel=amo.RELEASE_CHANNEL_UNLISTED)
        with self.settings(SIGNING_SERVER='full'):
            self.helper.handler.process_public()

        assert self.addon.status == amo.STATUS_NULL
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_PUBLIC)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s signed and ready to download' % self.preamble)
        assert 'our automatic tests and is now signed' in mail.outbox[0].body

        sign_mock.assert_called_with(self.file, 'full')
        assert storage.exists(self.file.mirror_file_path)

        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    @patch('olympia.editors.helpers.sign_file')
    def test_nomination_to_public_failed_signing(self, sign_mock):
        sign_mock.side_effect = Exception
        sign_mock.reset()
        self.setup_data(amo.STATUS_NOMINATED)
        with self.settings(SIGNING_SERVER='full'):
            with self.assertRaises(Exception):
                self.helper.handler.process_public()

        # Status unchanged.
        assert self.addon.status == amo.STATUS_NOMINATED
        assert self.addon.versions.all()[0].files.all()[0].status == (
            amo.STATUS_AWAITING_REVIEW)

        assert len(mail.outbox) == 0
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 0

    @patch('olympia.editors.helpers.sign_file')
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

        assert not sign_mock.called
        assert not storage.exists(self.file.mirror_file_path)
        assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_email_unicode_monster(self):
        self.addon.name = u'TaobaoShopping淘宝网导航按钮'
        self.addon.save()
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_sandbox()
        assert u'TaobaoShopping淘宝网导航按钮' in mail.outbox[0].subject

    def test_super_review_email(self):
        self.setup_data(amo.STATUS_NULL)
        self.helper.handler.process_super_review()
        url = reverse('editors.review', args=[self.addon.pk], add_prefix=False)
        assert url in mail.outbox[1].body

    def test_nomination_to_super_review(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.helper.handler.process_super_review()

        assert self.addon.admin_review

        assert len(mail.outbox) == 2
        assert mail.outbox[1].subject == (
            'Super review requested: Delicious Bookmarks')
        assert mail.outbox[0].subject == (
            ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
             'Admin Review'))
        assert self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id) == 1

    def test_nomination_to_super_review_and_escalate(self):
        self.setup_data(amo.STATUS_NOMINATED)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.helper.handler.process_super_review()

        assert self.addon.admin_review

        assert len(mail.outbox) == 2
        assert mail.outbox[1].subject == (
            'Super review requested: Delicious Bookmarks')
        assert mail.outbox[0].subject == (
            ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
             'Admin Review'))

        assert self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id) == 1

    @patch('olympia.editors.helpers.sign_file')
    def test_pending_to_public(self, sign_mock):
        self.setup_data(amo.STATUS_NOMINATED)
        self.create_paths()
        self.helper.handler.process_public()

        for file in self.helper.handler.data['addon_files']:
            assert file.status == amo.STATUS_PUBLIC

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            '%s Approved' % self.preamble)
        assert 'has been approved' in mail.outbox[0].body

        assert sign_mock.called
        assert storage.exists(self.file.mirror_file_path)
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

    @patch('olympia.editors.helpers.sign_file')
    def test_pending_to_sandbox(self, sign_mock):
        for status in amo.UNREVIEWED_ADDON_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_DISABLED

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s didn\'t pass review' % self.preamble)
            assert 'did not meet the criteria' in mail.outbox[0].body

            assert not sign_mock.called
            assert not storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_operating_system_present(self):
        self.setup_data(amo.STATUS_BETA)
        self.helper.handler.process_sandbox()

        assert 'Tested on osx with Firefox' in mail.outbox[0].body

    def test_operating_system_not_present(self):
        self.setup_data(amo.STATUS_BETA)
        data = self.get_data().copy()
        data['operating_systems'] = ''
        self.helper.set_data(data)
        self.helper.handler.process_sandbox()

        assert 'Tested with Firefox' in mail.outbox[0].body

    def test_application_not_present(self):
        self.setup_data(amo.STATUS_BETA)
        data = self.get_data().copy()
        data['applications'] = ''
        self.helper.set_data(data)
        self.helper.handler.process_sandbox()

        assert 'Tested on osx' in mail.outbox[0].body

    def test_both_not_present(self):
        self.setup_data(amo.STATUS_BETA)
        data = self.get_data().copy()
        data['applications'] = ''
        data['operating_systems'] = ''
        self.helper.set_data(data)
        self.helper.handler.process_sandbox()

        assert 'Tested' not in mail.outbox[0].body

    def test_pending_to_super_review(self):
        for status in helpers.PENDING_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()

            assert self.addon.admin_review

            assert len(mail.outbox) == 2
            assert mail.outbox[1].subject == (
                'Super review requested: Delicious Bookmarks')
            assert mail.outbox[0].subject == (
                ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
                 'Admin Review'))

    def test_nominated_review_time_set_version(self):
        for process in ('process_sandbox', 'process_public'):
            self.version.update(reviewed=None)
            self.setup_data(amo.STATUS_NOMINATED)
            getattr(self.helper.handler, process)()
            assert self.version.reload().reviewed

    def test_nominated_review_time_set_file(self):
        for process in ('process_sandbox', 'process_public'):
            self.file.update(reviewed=None)
            self.setup_data(amo.STATUS_NOMINATED)
            getattr(self.helper.handler, process)()
            assert File.objects.get(pk=self.file.pk).reviewed


def test_page_title_unicode():
    t = Translation(localized_string=u'\u30de\u30eb\u30c1\u30d712\u30eb')
    request = Mock()
    request.APP = amo.FIREFOX
    helpers.editor_page_title({'request': request}, title=t)


def test_send_email_autoescape():
    mock_request = Mock()
    mock_request.user = None
    base = helpers.ReviewBase(mock_request, None, None, '')
    s = 'woo&&<>\'""'
    ctx = dict(name=s, review_url=s, reviewer=s, comments=s, SITE_URL=s)
    base.get_context_data = Mock(name='get_context_data', return_value=ctx)
    base.data = {'comments': ''}

    # Make sure HTML is not auto-escaped.
    base.send_super_mail()
    assert len(mail.outbox) == 1
    assert mail.outbox[0].body.count(s) == len(ctx)


class TestCompareLink(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCompareLink, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.current = File.objects.get(pk=67442)
        self.version = Version.objects.create(addon=self.addon)

    def test_same_platform(self):
        file = File.objects.create(version=self.version,
                                   platform=self.current.platform)
        assert file.pk == helpers.file_compare(self.current, self.version).pk

    def test_different_platform(self):
        file = File.objects.create(version=self.version,
                                   platform=self.current.platform)
        File.objects.create(version=self.version,
                            platform=amo.PLATFORM_LINUX.id)
        assert file.pk == helpers.file_compare(self.current, self.version).pk

    def test_specific_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()

        linux = File.objects.create(version=self.version,
                                    platform=amo.PLATFORM_LINUX.id)
        assert linux.pk == helpers.file_compare(self.current, self.version).pk

    def test_no_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()
        file = File.objects.create(version=self.version,
                                   platform=amo.PLATFORM_WIN.id)
        assert file.pk == helpers.file_compare(self.current, self.version).pk


def test_version_status():
    addon = Addon()
    version = Version()
    version.all_files = [File(status=amo.STATUS_PUBLIC),
                         File(status=amo.STATUS_AWAITING_REVIEW)]
    assert u'Approved,Awaiting Review' == (
        helpers.version_status(addon, version))

    version.all_files = [File(status=amo.STATUS_AWAITING_REVIEW)]
    assert u'Awaiting Review' == helpers.version_status(addon, version)


def test_file_review_status_handles_invalid_status_id():
    # When status is a valid one, one of STATUS_CHOICES_FILE return label.
    assert amo.STATUS_CHOICES_FILE[amo.STATUS_PUBLIC] == (
        helpers.file_review_status(None, File(status=amo.STATUS_PUBLIC)))

    # 99 isn't a valid status, so return the status code for reference.
    assert u'[status:99]' == helpers.file_review_status(None, File(status=99))
