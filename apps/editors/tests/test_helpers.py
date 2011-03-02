# -*- coding: utf8 -*-

import os
from datetime import datetime, timedelta
import shutil
import tempfile

from django.core import mail
from django.conf import settings

from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from addons.models import Addon
import amo
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from editors.helpers import (ViewPendingQueueTable, ReviewHelper, ReviewFiles,
                             ReviewAddon, NOMINATED_STATUSES,
                             PRELIMINARY_STATUSES, PENDING_STATUSES)
from files.models import File
from users.models import UserProfile


REVIEW_ADDON_STATUSES = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                         amo.STATUS_UNREVIEWED)
REVIEW_FILES_STATUSES = (amo.STATUS_BETA, amo.STATUS_NULL, amo.STATUS_PUBLIC,
                         amo.STATUS_DISABLED, amo.STATUS_LISTED,
                         amo.STATUS_LITE)


class TestViewPendingQueueTable(test_utils.TestCase):

    def setUp(self):
        super(TestViewPendingQueueTable, self).setUp()
        qs = Mock()
        self.table = ViewPendingQueueTable(qs)

    def test_addon_name(self):
        row = Mock()
        page = Mock()
        page.start_index = Mock()
        page.start_index.return_value = 1
        row.addon_name = 'フォクすけといっしょ'.decode('utf8')
        row.latest_version = u'0.12'
        row.latest_version_id = 1234
        self.table.set_page(page)
        a = pq(self.table.render_addon_name(row))
        eq_(a.attr('href'),
            reverse('editors.review',
                    args=[row.latest_version_id]) + '?num=1')
        eq_(a.text(), "フォクすけといっしょ 0.12".decode('utf8'))

    def test_addon_type_id(self):
        row = Mock()
        row.addon_type_id = amo.ADDON_THEME
        eq_(unicode(self.table.render_addon_type_id(row)), u'Theme')

    def test_additional_info_site_specific(self):
        row = Mock()
        row.is_site_specific = True
        eq_(self.table.render_additional_info(row), u'Site Specific')

    def test_additional_info_for_platform(self):
        row = Mock()
        row.is_site_specific = False
        row.file_platform_ids = [amo.PLATFORM_LINUX.id]
        eq_(self.table.render_additional_info(row), u'Linux only')

    def test_additional_info_for_all_platforms(self):
        row = Mock()
        row.is_site_specific = False
        row.file_platform_ids = [amo.PLATFORM_ALL.id]
        eq_(self.table.render_additional_info(row), u'')

    def test_additional_info_for_mixed_platforms(self):
        row = Mock()
        row.is_site_specific = False
        row.file_platform_ids = [amo.PLATFORM_ALL.id, amo.PLATFORM_LINUX.id]
        eq_(self.table.render_additional_info(row), u'')

    def test_applications(self):
        row = Mock()
        row.application_ids = [amo.FIREFOX.id, amo.THUNDERBIRD.id]
        doc = pq(self.table.render_applications(row))
        eq_(sorted(a.attrib['class'] for a in doc('div div')),
            ['app-icon ed-sprite-firefox', 'app-icon ed-sprite-thunderbird'])

    def test_waiting_time_in_days(self):
        row = Mock()
        row.waiting_time_days = 10
        row.waiting_time_hours = 10 * 24
        eq_(self.table.render_waiting_time_days(row), u'10 days')

    def test_waiting_time_one_day(self):
        row = Mock()
        row.waiting_time_days = 1
        row.waiting_time_hours = 24
        eq_(self.table.render_waiting_time_days(row), u'1 day')

    def test_waiting_time_in_hours(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 22
        eq_(self.table.render_waiting_time_days(row), u'22 hours')

    def test_flags_admin_review(self):
        row = Mock()
        row.admin_review = True
        doc = pq(self.table.render_flags(row))
        eq_(doc('div').attr('class'), 'app-icon ed-sprite-admin-review')

    def test_no_flags(self):
        row = Mock()
        row.admin_review = False
        eq_(self.table.render_flags(row), '')


yesterday = datetime.today() - timedelta(days=1)


class TestReviewHelper(test_utils.TestCase):
    fixtures = ('base/addon_3615', 'base/users')
    preamble = 'Mozilla Add-ons: Delicious Bookmarks 2.1.072'

    def setUp(self):
        class FakeRequest:
            user = UserProfile.objects.get(pk=10482).user

        self.request = FakeRequest()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.files.all()[0]

        self.old_mirror = settings.MIRROR_STAGE_PATH
        self.old_normal = settings.ADDONS_PATH
        settings.MIRROR_STAGE_PATH = tempfile.mkdtemp()
        settings.ADDONS_PATH = tempfile.mkdtemp()

        os.mkdir(os.path.dirname(self.file.mirror_file_path))
        # Make local.
        if not os.path.exists(os.path.dirname(self.file.file_path)):
            os.mkdir(os.path.dirname(self.file.file_path))
        if not os.path.exists(self.file.file_path):
            open(self.file.file_path, 'w')

    def tearDown(self):
        shutil.rmtree(settings.MIRROR_STAGE_PATH)
        settings.MIRROR_STAGE_PATH = self.old_mirror
        settings.ADDONS_PATH = self.old_normal

    def get_data(self):
        return {'comments': 'foo', 'files': self.version.files.all(),
                'action': 'prelim', 'operating_systems': 'osx',
                'applications': 'Firefox'}

    def get_helper(self):
        return ReviewHelper(request=self.request, addon=self.addon,
                            version=self.version)

    def setup_type(self, status):
        self.addon.update(status=status)
        return self.get_helper().review_type

    def check_log_count(self, id):
        return (ActivityLog.objects.for_addons(self.helper.addon)
                                   .filter(action=id).count())

    def test_type_nominated(self):
        eq_(self.setup_type(amo.STATUS_NOMINATED), 'nominated')
        eq_(self.setup_type(amo.STATUS_LITE_AND_NOMINATED), 'nominated')

    def test_type_preliminary(self):
        eq_(self.setup_type(amo.STATUS_UNREVIEWED), 'preliminary')
        eq_(self.setup_type(amo.STATUS_LITE), 'preliminary')

    def test_type_pending(self):
        eq_(self.setup_type(amo.STATUS_PENDING), 'pending')
        eq_(self.setup_type(amo.STATUS_NULL), 'pending')
        eq_(self.setup_type(amo.STATUS_PUBLIC), 'pending')
        eq_(self.setup_type(amo.STATUS_DISABLED), 'pending')
        eq_(self.setup_type(amo.STATUS_LISTED), 'pending')
        eq_(self.setup_type(amo.STATUS_BETA), 'pending')
        eq_(self.setup_type(amo.STATUS_PURGATORY), 'pending')

    def test_review_files(self):
        for status in REVIEW_FILES_STATUSES:
            self.setup_data(status=status)
            eq_(self.helper.handler.__class__, ReviewFiles)

    def test_review_addon(self):
        for status in REVIEW_ADDON_STATUSES:
            self.setup_data(status=status)
            eq_(self.helper.handler.__class__, ReviewAddon)

    def test_process_action_none(self):
        self.helper.set_data({'action': 'foo'})
        self.assertRaises(self.helper.process)

    def test_process_action_good(self):
        self.helper.set_data({'action': 'info', 'comments': 'foo'})
        self.helper.process()
        eq_(len(mail.outbox), 1)

    def test_set_files(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.set_data({'files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['files'])

        self.file = self.version.files.all()[0]
        eq_(self.file.status, amo.STATUS_PUBLIC)
        assert self.file.datestatuschanged.date() > yesterday.date()

    def test_set_files_copy(self):
        self.helper.set_data({'files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['files'],
                                      copy_to_mirror=True)

        assert os.path.exists(self.file.mirror_file_path)

    def test_set_files_remove(self):
        open(self.file.mirror_file_path, 'wb')
        self.helper.set_data({'files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['files'],
                                      hide_disabled_file=True)

        assert not os.path.exists(self.file.mirror_file_path)

    def test_logs(self):
        self.helper.set_data({'comments': 'something'})
        self.helper.handler.log_status()
        self.helper.handler.log_approval(amo.LOG.APPROVE_VERSION)

        log = ActivityLog.objects.for_addons(self.helper.addon)
        eq_(log[0].action, amo.LOG.CHANGE_STATUS.id)
        eq_(log[1].action, amo.LOG.APPROVE_VERSION.id)

    def test_notify_email(self):
        self.helper.set_data(self.get_data())
        for template in ['nominated_to_nominated', 'nominated_to_preliminary',
                         'nominated_to_public', 'nominated_to_sandbox',
                         'pending_to_preliminary', 'pending_to_public',
                         'pending_to_sandbox', 'preliminary_to_preliminary']:
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            eq_(len(mail.outbox), 1)

    def setup_data(self, status, delete=[]):
        mail.outbox = []
        ActivityLog.objects.for_addons(self.helper.addon).delete()
        self.file.update(status=status)
        self.addon.status = status
        self.helper = self.get_helper()
        data = self.get_data().copy()
        for key in delete:
            del data[key]
        self.helper.set_data(data)

    def test_nomination_to_public_no_files(self):
        for status in NOMINATED_STATUSES:
            self.setup_data(status, ['files'])
            self.helper.handler.process_public()

            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_PUBLIC)

    def test_nomination_to_public_and_current_version(self):
        for status in NOMINATED_STATUSES:
            self.setup_data(status, ['files'])
            self.addon.update(_current_version=None)

            addon = Addon.objects.get(pk=3615)
            assert not addon.current_version
            self.helper.handler.process_public()
            assert addon.current_version

    def test_nomination_to_public(self):
        for status in NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_public()

            eq_(self.addon.status, amo.STATUS_PUBLIC)
            eq_(self.addon.highest_status, amo.STATUS_PUBLIC)
            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_PUBLIC)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Fully Reviewed' % self.preamble)

            assert os.path.exists(self.file.mirror_file_path)

            log = ActivityLog.objects.for_addons(self.helper.addon)
            eq_(len(log), 2)
            eq_(log[0].action, amo.LOG.CHANGE_STATUS.id)
            eq_(log[1].action, amo.LOG.APPROVE_VERSION.id)

    def test_nomination_to_preliminary(self):
        for status in NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_preliminary()

            eq_(self.addon.status, amo.STATUS_LITE)
            if status == amo.STATUS_LITE_AND_NOMINATED:
                eq_(self.addon.highest_status, amo.STATUS_LITE)
            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_LITE)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                '%s Preliminary Reviewed' % self.preamble)

            assert os.path.exists(self.file.mirror_file_path)

            eq_(self.check_log_count(amo.LOG.CHANGE_STATUS.id), 1)
            eq_(self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id), 1)

    def test_nomination_to_sandbox(self):
        for status in NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            eq_(self.addon.highest_status, amo.STATUS_PUBLIC)
            eq_(self.addon.status, amo.STATUS_NULL)
            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_DISABLED)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Reviewed' % self.preamble)

            assert not os.path.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.CHANGE_STATUS.id), 1)
            eq_(self.check_log_count(amo.LOG.REJECT_VERSION.id), 1)

    def test_nomination_to_super_review(self):
        for status in NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                'Super review requested: Delicious Bookmarks')

    def test_unreviewed_to_public(self):
        self.setup_data(amo.STATUS_UNREVIEWED)
        self.assertRaises(AssertionError,
                          self.helper.handler.process_public)

    def test_lite_to_public(self):
        self.setup_data(amo.STATUS_LITE)
        assert not hasattr(self.helper.handler, 'process_public')

    def test_preliminary_to_preliminary(self):
        for status in PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_preliminary()

            for file in self.helper.handler.data['files']:
                eq_(file.status, amo.STATUS_LITE)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                '%s Preliminary Reviewed' % self.preamble)

            assert os.path.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id), 1)

    def test_preliminary_to_sandbox(self):
        for status in PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['files']:
                eq_(file.status, amo.STATUS_DISABLED)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Reviewed' % self.preamble)

            assert not os.path.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.REJECT_VERSION.id), 1)

    def test_preliminary_to_super_review(self):
        for status in PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                'Super review requested: Delicious Bookmarks')

    def test_nomination_to_super_review_and_escalate(self):
        # Note we are changing the file status here.
        for file_status in (amo.STATUS_PENDING, amo.STATUS_UNREVIEWED):
            self.setup_data(amo.STATUS_LITE)
            self.file.update(status=file_status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                'Super review requested: Delicious Bookmarks')

            eq_(self.check_log_count(amo.LOG.ESCALATE_VERSION.id), 1)

    def test_pending_to_public(self):
        for status in PENDING_STATUSES:
            self.setup_data(status)
            assert not hasattr(self.helper.handler, 'process_public')

    def test_pending_to_sandbox(self):
        for status in PENDING_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['files']:
                eq_(file.status, amo.STATUS_DISABLED)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Reviewed' % self.preamble)

            assert not os.path.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.REJECT_VERSION.id), 1)

    def test_pending_to_super_review(self):
        for status in PENDING_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                'Super review requested: Delicious Bookmarks')

    def test_nominated_review_time_set(self):
        for status in REVIEW_ADDON_STATUSES:
            for process in ['process_sandbox', 'process_preliminary',
                            'process_public']:
                if (status == amo.STATUS_UNREVIEWED
                    and process == 'process_public'):
                    continue
                self.version.update(reviewed=None)
                self.setup_data(status)
                getattr(self.helper.handler, process)()
                assert self.version.reviewed, ('Reviewed for status %r, %s()'
                                               % (status, process))

    def test_preliminary_review_time_set(self):
        for status in REVIEW_FILES_STATUSES:
            for process in ['process_sandbox', 'process_preliminary']:
                self.file.update(reviewed=None)
                self.setup_data(status)
                getattr(self.helper.handler, process)()
                assert File.objects.get(pk=self.file.pk).reviewed, (
                       'Reviewed for status %r, %s()' % (status, process))
