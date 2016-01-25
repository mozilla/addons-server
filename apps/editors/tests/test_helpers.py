# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.core import mail
from django.core.files.storage import default_storage as storage

import pytest
from mock import Mock, patch
from pyquery import PyQuery as pq

import amo
import amo.tests
from addons.models import Addon
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from editors import helpers
from editors.models import ReviewerScore
from files.models import File
from translations.models import Translation
from users.models import UserProfile
from versions.models import Version

from . test_models import create_addon_file


pytestmark = pytest.mark.django_db


REVIEW_ADDON_STATUSES = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                         amo.STATUS_UNREVIEWED)
REVIEW_FILES_STATUSES = (amo.STATUS_PUBLIC,
                         amo.STATUS_DISABLED, amo.STATUS_LITE)


class TestViewPendingQueueTable(amo.tests.TestCase):

    def setUp(self):
        super(TestViewPendingQueueTable, self).setUp()
        qs = Mock()
        self.table = helpers.ViewPendingQueueTable(qs)

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
        assert a.attr('href') == reverse('editors.review', args=[str(row.addon_slug)])
        assert a.text() == "フォクすけといっしょ 0.12".decode('utf8')

    def test_addon_type_id(self):
        row = Mock()
        row.addon_type_id = amo.ADDON_THEME
        assert unicode(self.table.render_addon_type_id(row)) == u'Complete Theme'

    def test_applications(self):
        row = Mock()
        row.application_ids = [amo.FIREFOX.id, amo.THUNDERBIRD.id]
        doc = pq(self.table.render_applications(row))
        assert sorted(a.attrib['class'] for a in doc('div div')) == ['app-icon ed-sprite-firefox', 'app-icon ed-sprite-thunderbird']

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


class TestAdditionalInfoInQueue(amo.tests.TestCase):

    def setUp(self):
        super(TestAdditionalInfoInQueue, self).setUp()
        qs = Mock()
        self.table = helpers.ViewPendingQueueTable(qs)
        self.row = Mock()
        self.row.is_site_specific = False
        self.row.file_platform_ids = [amo.PLATFORM_ALL.id]
        self.row.external_software = False
        self.row.binary = False
        self.row.binary_components = False

    def test_no_info(self):
        assert self.table.render_additional_info(self.row) == ''

    def test_site_specific(self):
        self.row.is_site_specific = True
        assert self.table.render_additional_info(self.row) == u'Site Specific'

    def test_platform(self):
        self.row.file_platform_ids = [amo.PLATFORM_LINUX.id]
        assert "plat-sprite-linux" in self.table.render_platforms(self.row)

    def test_combo(self):
        self.row.is_site_specific = True
        self.row.external_software = True
        assert self.table.render_additional_info(self.row) == u'Site Specific, Requires External Software'

    def test_all_platforms(self):
        self.row.file_platform_ids = [amo.PLATFORM_ALL.id]
        assert "plat-sprite-all" in self.table.render_platforms(self.row)

    def test_mixed_platforms(self):
        self.row.file_platform_ids = [amo.PLATFORM_ALL.id,
                                      amo.PLATFORM_LINUX.id]
        assert "plat-sprite-linux" in self.table.render_platforms(self.row)
        assert "plat-sprite-all" in self.table.render_platforms(self.row)

    def test_external_software(self):
        self.row.external_software = True
        assert self.table.render_additional_info(self.row) == u'Requires External Software'

    def test_binary(self):
        self.row.binary = True
        assert self.table.render_additional_info(self.row) == u'Binary Components'


yesterday = datetime.today() - timedelta(days=1)


class TestReviewHelper(amo.tests.TestCase):
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
                'action': 'prelim', 'operating_systems': 'osx',
                'applications': 'Firefox'}

    def get_helper(self):
        return helpers.ReviewHelper(request=self.request, addon=self.addon,
                                    version=self.version)

    def setup_type(self, status):
        self.addon.update(status=status)
        return self.get_helper().review_type

    def check_log_count(self, id):
        return (ActivityLog.objects.for_addons(self.helper.addon)
                                   .filter(action=id).count())

    def test_type_nominated(self):
        assert self.setup_type(amo.STATUS_NOMINATED) == 'nominated'
        assert self.setup_type(amo.STATUS_LITE_AND_NOMINATED) == 'nominated'

    def test_type_preliminary(self):
        assert self.setup_type(amo.STATUS_UNREVIEWED) == 'preliminary'
        assert self.setup_type(amo.STATUS_LITE) == 'preliminary'

    def test_type_pending(self):
        assert self.setup_type(amo.STATUS_PENDING) == 'pending'
        assert self.setup_type(amo.STATUS_NULL) == 'pending'
        assert self.setup_type(amo.STATUS_PUBLIC) == 'pending'
        assert self.setup_type(amo.STATUS_DISABLED) == 'pending'
        assert self.setup_type(amo.STATUS_BETA) == 'pending'
        assert self.setup_type(amo.STATUS_PURGATORY) == 'pending'

    def test_no_version(self):
        helper = helpers.ReviewHelper(request=self.request, addon=self.addon,
                                      version=None)
        assert helper.review_type == 'pending'

    def test_review_files(self):
        for status in REVIEW_FILES_STATUSES:
            self.setup_data(status=status)
            assert self.helper.handler.__class__ == helpers.ReviewFiles

    def test_review_addon(self):
        for status in REVIEW_ADDON_STATUSES:
            self.setup_data(status=status)
            assert self.helper.handler.__class__ == helpers.ReviewAddon

    def test_process_action_none(self):
        self.helper.set_data({'action': 'foo'})
        with pytest.raises(Exception):
            self.helper.process()

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

    def get_action(self, status, action):
        self.addon.update(status=status)
        return unicode(self.get_helper().actions[action]['details'])

    def test_action_changes(self):
        assert self.get_action(amo.STATUS_LITE, 'reject')[:26] == 'This will reject the files'
        assert self.get_action(amo.STATUS_UNREVIEWED, 'reject')[:27] == 'This will reject the add-on'
        assert self.get_action(amo.STATUS_UNREVIEWED, 'prelim')[:25] == 'This will mark the add-on'
        assert self.get_action(amo.STATUS_NOMINATED, 'prelim')[:25] == 'This will mark the add-on'
        assert self.get_action(amo.STATUS_LITE, 'prelim')[:24] == 'This will mark the files'
        assert self.get_action(amo.STATUS_LITE_AND_NOMINATED, 'prelim')[:27] == 'This will retain the add-on'
        assert self.get_action(amo.STATUS_NULL, 'reject')[:26] == 'This will reject a version'
        assert self.get_action(amo.STATUS_NOMINATED, 'public')[-31:] == 'they are reviewed by an editor.'
        assert self.get_action(amo.STATUS_PUBLIC, 'public')[-29:] == 'to appear on the public side.'

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
        for template in ['nominated_to_nominated', 'nominated_to_preliminary',
                         'nominated_to_public', 'nominated_to_sandbox',
                         'pending_to_preliminary', 'pending_to_public',
                         'pending_to_sandbox', 'preliminary_to_preliminary',
                         'author_super_review', 'unlisted_to_reviewed',
                         'unlisted_to_reviewed_auto',
                         'unlisted_to_sandbox']:
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            assert len(mail.outbox) == 1
            assert mail.outbox[0].body, 'Expected a message'

    def setup_data(self, status, delete=[], is_listed=True):
        mail.outbox = []
        ActivityLog.objects.for_addons(self.helper.addon).delete()
        self.addon.update(status=status, is_listed=is_listed)
        self.file.update(status=status)
        self.helper = self.get_helper()
        data = self.get_data().copy()
        for key in delete:
            del data[key]
        self.helper.set_data(data)

    def test_request_more_information(self):
        self.setup_data(amo.STATUS_PUBLIC, ['addon_files'])
        self.helper.handler.request_information()
        assert self.version.has_info_request is True
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == self.preamble
        assert self.check_log_count(amo.LOG.REQUEST_INFORMATION.id) == 1

    def test_email_no_locale(self):
        self.setup_data(amo.STATUS_NOMINATED, ['addon_files'])
        self.helper.handler.process_public()
        assert len(mail.outbox) == 1
        assert '/en-US/firefox/addon/a3615' not in mail.outbox[0].body
        assert '/addon/a3615' in mail.outbox[0].body

    def test_nomination_to_public_no_files(self):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status, ['addon_files'])
            self.helper.handler.process_public()
            assert self.addon.versions.all()[0].files.all()[0].status == amo.STATUS_PUBLIC

    def test_nomination_to_public_and_current_version(self):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status, ['addon_files'])
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
            i.files.update(status=amo.STATUS_UNREVIEWED)

        self.helper.handler.process_public()

        # Re-fetch the add-on
        addon = Addon.objects.get(pk=3615)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.highest_status == amo.STATUS_PUBLIC
        assert addon.versions.all()[0].files.all()[0].status == amo.STATUS_PUBLIC
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == '%s Fully Reviewed' % self.preamble

        assert storage.exists(self.file.mirror_file_path)
        assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

        self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('editors.helpers.sign_file')
    def test_nomination_to_public(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status)
            with self.settings(SIGNING_SERVER='full'):
                self.helper.handler.process_public()

            assert self.addon.status == amo.STATUS_PUBLIC
            assert self.addon.highest_status == amo.STATUS_PUBLIC
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_PUBLIC)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s Fully Reviewed' % self.preamble)
            assert 'has been fully reviewed' in mail.outbox[0].body

            sign_mock.assert_called_with(self.file, 'full')
            assert storage.exists(self.file.mirror_file_path)

            assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

            self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('editors.helpers.sign_file')
    def test_nomination_to_public_unlisted(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status, is_listed=False)
            with self.settings(SIGNING_SERVER='full'):
                self.helper.handler.process_public()

            assert self.addon.status == amo.STATUS_PUBLIC
            assert self.addon.highest_status == amo.STATUS_PUBLIC
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_PUBLIC)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s signed and ready to download' % self.preamble)
            assert 'has been reviewed and is now signed' in mail.outbox[0].body

            sign_mock.assert_called_with(self.file, 'full')
            assert storage.exists(self.file.mirror_file_path)

            assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

            self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('editors.helpers.sign_file')
    def test_nomination_to_public_failed_signing(self, sign_mock):
        sign_mock.side_effect = Exception
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status)
            with self.settings(SIGNING_SERVER='full'):
                with pytest.raises(Exception):
                    self.helper.handler.process_public()

            # Status unchanged.
            assert self.addon.status == status
            assert self.addon.versions.all()[0].files.all()[0].status == status

            assert len(mail.outbox) == 0
            assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 0

    @patch('editors.helpers.sign_file')
    def test_nomination_to_preliminary(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status)
            with self.settings(PRELIMINARY_SIGNING_SERVER='prelim'):
                self.helper.handler.process_preliminary()

            assert self.addon.status == amo.STATUS_LITE
            if status == amo.STATUS_LITE_AND_NOMINATED:
                assert self.addon.highest_status == amo.STATUS_LITE
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_LITE)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s Preliminary Reviewed' % self.preamble)
            assert 'has been granted preliminary review' in mail.outbox[0].body

            sign_mock.assert_called_with(self.file, 'prelim')
            assert storage.exists(self.file.mirror_file_path)

            assert self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id) == 1

            self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('editors.helpers.sign_file')
    def test_nomination_to_preliminary_unlisted(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status, is_listed=False)
            with self.settings(PRELIMINARY_SIGNING_SERVER='prelim'):
                self.helper.handler.process_preliminary()

            assert self.addon.status == amo.STATUS_LITE
            if status == amo.STATUS_LITE_AND_NOMINATED:
                assert self.addon.highest_status == amo.STATUS_LITE
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_LITE)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s signed and ready to download' % self.preamble)
            assert 'has been reviewed and is now signed' in mail.outbox[0].body

            sign_mock.assert_called_with(self.file, 'prelim')
            assert storage.exists(self.file.mirror_file_path)

            assert self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id) == 1

            self._check_score(amo.REVIEWED_ADDON_FULL)

    @patch('editors.helpers.sign_file')
    def test_nomination_to_preliminary_unlisted_auto(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status, is_listed=False)
            with self.settings(PRELIMINARY_SIGNING_SERVER='prelim'):
                self.helper.handler.process_preliminary(auto_validation=True)

            assert self.addon.status == amo.STATUS_LITE
            if status == amo.STATUS_LITE_AND_NOMINATED:
                assert self.addon.highest_status == amo.STATUS_LITE
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_LITE)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s signed and ready to download' % self.preamble)
            assert 'has passed our automatic tests' in mail.outbox[0].body

            sign_mock.assert_called_with(self.file, 'prelim')
            assert storage.exists(self.file.mirror_file_path)

            assert self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id) == 1

            assert not ReviewerScore.objects.all()

    @patch('editors.helpers.sign_file')
    def test_nomination_to_preliminary_failed_signing(self, sign_mock):
        sign_mock.side_effect = Exception
        for status in helpers.NOMINATED_STATUSES:
            sign_mock.reset()
            self.setup_data(status)
            with pytest.raises(Exception):
                self.helper.handler.process_preliminary()

            # Status unchanged.
            assert self.addon.status == status
            assert self.addon.versions.all()[0].files.all()[0].status == status

            assert len(mail.outbox) == 0
            assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 0

    @patch('editors.helpers.sign_file')
    def test_nomination_to_sandbox(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            assert self.addon.highest_status == amo.STATUS_PUBLIC
            assert self.addon.status == amo.STATUS_NULL
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_DISABLED)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == '%s Rejected' % self.preamble
            assert 'did not meet the criteria' in mail.outbox[0].body

            assert not sign_mock.called
            assert not storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    @patch('editors.helpers.sign_file')
    def test_nomination_to_sandbox_unlisted(self, sign_mock):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status, is_listed=False)
            self.helper.handler.process_sandbox()

            assert self.addon.highest_status == amo.STATUS_PUBLIC
            assert self.addon.status == amo.STATUS_NULL
            assert self.addon.versions.all()[0].files.all()[0].status == (
                amo.STATUS_DISABLED)

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s didn\'t pass review' % self.preamble)
            assert 'didn\'t pass review' in mail.outbox[0].body

            assert not sign_mock.called
            assert not storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_email_unicode_monster(self):
        self.addon.name = u'TaobaoShopping淘宝网导航按钮'
        self.addon.save()
        self.setup_data(helpers.NOMINATED_STATUSES[0])
        self.helper.handler.process_sandbox()
        assert u'TaobaoShopping淘宝网导航按钮' in mail.outbox[0].subject

    def test_super_review_email(self):
        self.setup_data(amo.STATUS_NULL)
        self.helper.handler.process_super_review()
        url = reverse('editors.review', args=[self.addon.pk], add_prefix=False)
        assert url in mail.outbox[1].body

    def test_nomination_to_super_review(self):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()
            assert self.addon.admin_review is True
            assert len(mail.outbox) == 2
            assert mail.outbox[1].subject == 'Super review requested: Delicious Bookmarks'
            assert mail.outbox[0].subject == ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for ' 'Admin Review')
            assert self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id) == 1

    def test_unreviewed_to_public(self):
        self.setup_data(amo.STATUS_UNREVIEWED)
        with pytest.raises(AssertionError):
            self.helper.handler.process_public()

    def test_lite_to_public(self):
        self.setup_data(amo.STATUS_LITE)
        with pytest.raises(AssertionError):
            self.helper.handler.process_public()

    @patch('editors.helpers.sign_file')
    def test_preliminary_to_preliminary(self, sign_mock):
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_preliminary()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_LITE

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s Preliminary Reviewed' % self.preamble)
            assert 'has been preliminarily reviewed' in mail.outbox[0].body

            assert sign_mock.called
            assert storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id) == 1

            self._check_score(amo.REVIEWED_ADDON_PRELIM)

    @patch('editors.helpers.sign_file')
    def test_preliminary_to_preliminary_unlisted(self, sign_mock):
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status, is_listed=False)
            self.helper.handler.process_preliminary()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_LITE

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s signed and ready to download' % self.preamble)
            assert 'has been reviewed and is now signed' in mail.outbox[0].body

            assert sign_mock.called
            assert storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id) == 1

            self._check_score(amo.REVIEWED_ADDON_PRELIM)

    @patch('editors.helpers.sign_file')
    def test_preliminary_to_preliminary_unlisted_auto(self, sign_mock):
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status, is_listed=False)
            self.helper.handler.process_preliminary(auto_validation=True)

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_LITE

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s signed and ready to download' % self.preamble)
            assert 'has passed our automatic tests' in mail.outbox[0].body

            assert sign_mock.called
            assert storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id) == 1

            assert not ReviewerScore.objects.all()

    @patch('editors.helpers.sign_file')
    def test_preliminary_to_sandbox(self, sign_mock):
        for status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE_AND_NOMINATED]:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_DISABLED

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == '%s Rejected' % self.preamble
            assert 'did not meet the criteria' in mail.outbox[0].body

            assert not sign_mock.called
            assert not storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    @patch('editors.helpers.sign_file')
    def test_preliminary_to_sandbox_unlisted(self, sign_mock):
        for status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE_AND_NOMINATED]:
            self.setup_data(status, is_listed=False)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_DISABLED

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s didn\'t pass review' % self.preamble)
            assert 'didn\'t pass review' in mail.outbox[0].body

            assert not sign_mock.called
            assert not storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    def test_preliminary_upgrade_to_sandbox(self):
        self.setup_data(amo.STATUS_LITE)
        assert self.addon.status == amo.STATUS_LITE
        assert self.file.status == amo.STATUS_LITE

        a = create_addon_file(self.addon.name, '2.2', amo.STATUS_LITE,
                              amo.STATUS_UNREVIEWED)
        self.version = a['version']

        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.helper = self.get_helper()
        self.helper.set_data(self.get_data())

        self.helper.handler.process_sandbox()
        assert self.addon.status == amo.STATUS_LITE
        assert self.file.status == amo.STATUS_LITE
        f = File.objects.get(pk=a['file'].id)
        assert f.status == amo.STATUS_DISABLED

    def test_preliminary_to_super_review(self):
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()
            assert self.addon.admin_review is True
            assert len(mail.outbox) == 2
            assert mail.outbox[1].subject == 'Super review requested: Delicious Bookmarks'
            assert mail.outbox[0].subject == ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for ' 'Admin Review')
            assert self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id) == 1

    def test_nomination_to_super_review_and_escalate(self):
        # Note we are changing the file status here.
        for file_status in (amo.STATUS_PENDING, amo.STATUS_UNREVIEWED):
            self.setup_data(amo.STATUS_LITE)
            self.file.update(status=file_status)
            self.helper.handler.process_super_review()
            assert self.addon.admin_review is True
            assert len(mail.outbox) == 2
            assert mail.outbox[1].subject == 'Super review requested: Delicious Bookmarks'
            assert mail.outbox[0].subject == ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for ' 'Admin Review')
            assert self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id) == 1

    @patch('editors.helpers.sign_file')
    def test_pending_to_public(self, sign_mock):
        for status in [amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED]:
            self.setup_data(status)
            self.create_paths()
            self.helper.handler.process_public()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_PUBLIC

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s Fully Reviewed' % self.preamble)
            assert 'has been fully reviewed' in mail.outbox[0].body

            assert sign_mock.called
            assert storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

            if status == amo.STATUS_PUBLIC:
                self._check_score(amo.REVIEWED_ADDON_UPDATE)

    @patch('editors.helpers.sign_file')
    def test_pending_to_public_unlisted(self, sign_mock):
        for status in [amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED]:
            self.setup_data(status, is_listed=False)
            self.create_paths()
            self.helper.handler.process_public()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_PUBLIC

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s signed and ready to download' % self.preamble)
            assert 'has been reviewed and is now signed' in mail.outbox[0].body

            assert sign_mock.called
            assert storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.APPROVE_VERSION.id) == 1

            if status == amo.STATUS_PUBLIC:
                self._check_score(amo.REVIEWED_ADDON_UPDATE)

    @patch('editors.helpers.sign_file')
    def test_pending_to_sandbox(self, sign_mock):
        for status in amo.UNDER_REVIEW_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_DISABLED

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == '%s Rejected' % self.preamble
            assert 'did not meet the criteria' in mail.outbox[0].body

            assert not sign_mock.called
            assert not storage.exists(self.file.mirror_file_path)
            assert self.check_log_count(amo.LOG.REJECT_VERSION.id) == 1

    @patch('editors.helpers.sign_file')
    def test_pending_to_sandbox_unlisted(self, sign_mock):
        for status in amo.UNDER_REVIEW_STATUSES:
            self.setup_data(status, is_listed=False)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                assert file.status == amo.STATUS_DISABLED

            assert len(mail.outbox) == 1
            assert mail.outbox[0].subject == (
                '%s didn\'t pass review' % self.preamble)
            assert 'didn\'t pass review' in mail.outbox[0].body

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
            assert self.addon.admin_review is True
            assert len(mail.outbox) == 2
            assert mail.outbox[1].subject == 'Super review requested: Delicious Bookmarks'
            assert mail.outbox[0].subject == ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for ' 'Admin Review')

    def test_nominated_review_time_set(self):
        for status in REVIEW_ADDON_STATUSES:
            for process in ['process_sandbox', 'process_preliminary',
                            'process_public']:
                if (status == amo.STATUS_UNREVIEWED and
                        process == 'process_public'):
                    continue
                self.version.update(reviewed=None)
                self.setup_data(status)
                getattr(self.helper.handler, process)()
                assert self.version.reviewed, ('Reviewed for status %r, %s()'
                                               % (status, process))

    def test_preliminary_review_time_set(self):
        for status in amo.UNDER_REVIEW_STATUSES:
            for process in ['process_sandbox', 'process_preliminary']:
                self.file.update(reviewed=None)
                self.setup_data(status)
                getattr(self.helper.handler, process)()
                assert File.objects.get(pk=self.file.pk).reviewed, (
                    'Reviewed for status %r, %s()' % (status, process))


def test_page_title_unicode():
    t = Translation(localized_string=u'\u30de\u30eb\u30c1\u30d712\u30eb')
    request = Mock()
    request.APP = amo.FIREFOX
    helpers.editor_page_title({'request': request}, title=t)


def test_send_email_autoescape():
    # Make sure HTML is not auto-escaped.
    s = 'woo&&<>\'""'
    ctx = dict(name=s, review_url=s, reviewer=s, comments=s, SITE_URL=s)
    helpers.send_mail('editors/emails/super_review.ltxt',
                      'aww yeah', ['xx'], ctx)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].body.count(s) == len(ctx)


class TestCompareLink(amo.tests.TestCase):
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
                         File(status=amo.STATUS_UNREVIEWED)]
    assert u'Fully Reviewed,Awaiting Review' == helpers.version_status(addon, version)

    version.all_files = [File(status=amo.STATUS_UNREVIEWED)]
    assert u'Awaiting Review' == helpers.version_status(addon, version)
