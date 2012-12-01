# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from django.core import mail
from django.core.files.storage import default_storage as storage
from django.conf import settings

from mock import Mock
from nose.tools import eq_
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

REVIEW_ADDON_STATUSES = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                         amo.STATUS_UNREVIEWED)
REVIEW_FILES_STATUSES = (amo.STATUS_BETA, amo.STATUS_NULL, amo.STATUS_PUBLIC,
                         amo.STATUS_DISABLED, amo.STATUS_LISTED,
                         amo.STATUS_LITE)


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
        row.latest_version_id = 1234
        self.table.set_page(page)
        a = pq(self.table.render_addon_name(row))

        eq_(a.attr('href'),
            reverse('editors.review', args=[str(row.addon_slug)]) + '?num=1')
        eq_(a.text(), "フォクすけといっしょ 0.12".decode('utf8'))

    def test_addon_type_id(self):
        row = Mock()
        row.addon_type_id = amo.ADDON_THEME
        eq_(unicode(self.table.render_addon_type_id(row)), u'Theme')

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
        eq_(self.table.render_waiting_time_min(row), u'10 days')

    def test_waiting_time_one_day(self):
        row = Mock()
        row.waiting_time_days = 1
        row.waiting_time_hours = 24
        row.waiting_time_min = 60 * 24
        eq_(self.table.render_waiting_time_min(row), u'1 day')

    def test_waiting_time_in_hours(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 22
        row.waiting_time_min = 60 * 22
        eq_(self.table.render_waiting_time_min(row), u'22 hours')

    def test_waiting_time_in_min(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 0
        row.waiting_time_min = 11
        eq_(self.table.render_waiting_time_min(row), u'11 minutes')

    def test_waiting_time_in_secs(self):
        row = Mock()
        row.waiting_time_days = 0
        row.waiting_time_hours = 0
        row.waiting_time_min = 0
        eq_(self.table.render_waiting_time_min(row), u'moments ago')

    def test_flags_admin_review(self):
        row = Mock()
        row.admin_review = True
        doc = pq(self.table.render_flags(row))
        assert doc('div.ed-sprite-admin-review').length

    def test_flags_info_request(self):
        row = Mock()
        row.has_info_request = True
        doc = pq(self.table.render_flags(row))
        assert doc('div.ed-sprite-info').length

    def test_flags_editor_comment(self):
        row = Mock()
        row.has_editor_comment = True
        doc = pq(self.table.render_flags(row))
        assert doc('div.ed-sprite-editor').length

    def test_flags_jetpack_and_restartless(self):
        row = Mock()
        row.is_jetpack = True
        row.is_restartless = True
        doc = pq(self.table.render_flags(row))
        eq_(doc('div.ed-sprite-jetpack').length, 1)
        eq_(doc('div.ed-sprite-restartless').length, 0)

    def test_flags_restartless(self):
        row = Mock()
        row.is_restartless = True
        row.is_jetpack = False
        doc = pq(self.table.render_flags(row))
        eq_(doc('div.ed-sprite-jetpack').length, 0)
        eq_(doc('div.ed-sprite-restartless').length, 1)

    def test_flags_jetpack(self):
        row = Mock()
        row.is_jetpack = True
        doc = pq(self.table.render_flags(row))
        eq_(doc('div.ed-sprite-restartless').length, 0)
        eq_(doc('div.ed-sprite-jetpack').length, 1)

    def test_no_flags(self):
        row = Mock()
        row.is_restartless = False
        row.is_jetpack = False
        row.admin_review = False
        row.has_editor_comment = False
        row.has_info_request = False
        row.is_premium = False
        eq_(self.table.render_flags(row), '')


class TestAdditionalInfoInQueue(amo.tests.TestCase):

    def setUp(self):
        super(TestAdditionalInfoInQueue, self).setUp()
        qs = Mock()
        self.table = helpers.ViewPendingQueueTable(qs)
        self.row = Mock()
        self.row.latest_version_id = 1
        self.row.is_site_specific = False
        self.row.file_platform_ids = [self.platform_id(amo.PLATFORM_ALL.id)]
        self.row.file_platform_vers = [self.platform_id(amo.PLATFORM_ALL.id)]
        self.row.external_software = False
        self.row.binary = False
        self.row.binary_components = False

    def platform_id(self, platform):
        return '%s-%s' % (platform, self.row.latest_version_id)

    def test_no_info(self):
        eq_(self.table.render_additional_info(self.row), '')

    def test_site_specific(self):
        self.row.is_site_specific = True
        eq_(self.table.render_additional_info(self.row), u'Site Specific')

    def test_platform(self):
        self.row.file_platform_vers = [self.platform_id(amo.PLATFORM_LINUX.id)]
        assert "plat-sprite-linux" in self.table.render_platforms(self.row)

    def test_combo(self):
        self.row.is_site_specific = True
        self.row.external_software = True
        eq_(self.table.render_additional_info(self.row),
            u'Site Specific, Requires External Software')

    def test_all_platforms(self):
        self.row.file_platform_vers = [self.platform_id(amo.PLATFORM_ALL.id)]
        assert "plat-sprite-all" in self.table.render_platforms(self.row)

    def test_mixed_platforms(self):
        self.row.file_platform_vers = [self.platform_id(amo.PLATFORM_ALL.id),
                                       self.platform_id(amo.PLATFORM_LINUX.id)]
        assert "plat-sprite-linux" in self.table.render_platforms(self.row)
        assert "plat-sprite-all" in self.table.render_platforms(self.row)

    def test_external_software(self):
        self.row.external_software = True
        eq_(self.table.render_additional_info(self.row),
            u'Requires External Software')

    def test_binary(self):
        self.row.binary = True
        eq_(self.table.render_additional_info(self.row), u'Binary Components')


yesterday = datetime.today() - timedelta(days=1)


class TestReviewHelper(amo.tests.TestCase):
    fixtures = ('base/addon_3615', 'base/users')
    preamble = 'Mozilla Add-ons: Delicious Bookmarks 2.1.072'

    def setUp(self):
        class FakeRequest:
            amo_user = UserProfile.objects.get(pk=10482)
            user = amo_user.user

        self.request = FakeRequest()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.versions.all()[0]
        self.helper = self.get_helper()
        self.file = self.version.files.all()[0]

        self.old_mirror = settings.MIRROR_STAGE_PATH
        self.old_normal = settings.ADDONS_PATH

        self.create_paths()

    def _check_score(self, reviewed_type):
        scores = ReviewerScore.objects.all()
        assert len(scores) > 0
        eq_(scores[0].score, amo.REVIEWED_SCORES[reviewed_type])
        eq_(scores[0].note_key, reviewed_type)

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
            eq_(self.helper.handler.__class__, helpers.ReviewFiles)

    def test_review_addon(self):
        for status in REVIEW_ADDON_STATUSES:
            self.setup_data(status=status)
            eq_(self.helper.handler.__class__, helpers.ReviewAddon)

    def test_process_action_none(self):
        self.helper.set_data({'action': 'foo'})
        self.assertRaises(self.helper.process)

    def test_process_action_good(self):
        self.helper.set_data({'action': 'info', 'comments': 'foo'})
        self.helper.process()
        eq_(len(mail.outbox), 1)

    def test_action_details(self):
        for status in amo.STATUS_CHOICES:
            self.addon.update(status=status)
            helper = self.get_helper()
            actions = helper.actions
            for k, v in actions.items():
                assert unicode(v['details']), "Missing details for: %s" % k

    def get_action(self, status, action):
        self.addon.update(status=status)
        return unicode(self.get_helper().actions[action]['details'])

    def test_action_changes(self):
        eq_(self.get_action(amo.STATUS_LITE, 'reject')[:26],
            'This will reject the files')
        eq_(self.get_action(amo.STATUS_UNREVIEWED, 'reject')[:27],
            'This will reject the add-on')
        eq_(self.get_action(amo.STATUS_UNREVIEWED, 'prelim')[:25],
            'This will mark the add-on')
        eq_(self.get_action(amo.STATUS_NOMINATED, 'prelim')[:25],
            'This will mark the add-on')
        eq_(self.get_action(amo.STATUS_LITE, 'prelim')[:24],
            'This will mark the files')
        eq_(self.get_action(amo.STATUS_LITE_AND_NOMINATED, 'prelim')[:27],
            'This will retain the add-on')
        eq_(self.get_action(amo.STATUS_NULL, 'reject')[:26],
            'This will reject a version')
        eq_(self.get_action(amo.STATUS_NOMINATED, 'public')[-31:],
            'they are reviewed by an editor.')
        eq_(self.get_action(amo.STATUS_PUBLIC, 'public')[-29:],
            'to appear on the public side.')

    def test_action_premium(self):
        for type_ in amo.ADDON_PREMIUMS:
            self.addon.update(premium_type=type_)
            self.assertRaises(KeyError, self.get_action,
                              amo.STATUS_NOMINATED, 'prelim')

    def test_set_files(self):
        self.file.update(datestatuschanged=yesterday)
        self.helper.set_data({'addon_files': self.version.files.all()})
        self.helper.handler.set_files(amo.STATUS_PUBLIC,
                                      self.helper.handler.data['addon_files'])

        self.file = self.version.files.all()[0]
        eq_(self.file.status, amo.STATUS_PUBLIC)
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
        eq_(self.check_log_count(amo.LOG.APPROVE_VERSION.id), 1)

    def test_notify_email(self):
        self.helper.set_data(self.get_data())
        for template in ['nominated_to_nominated', 'nominated_to_preliminary',
                         'nominated_to_public', 'nominated_to_sandbox',
                         'pending_to_preliminary', 'pending_to_public',
                         'pending_to_sandbox', 'preliminary_to_preliminary',
                         'author_super_review']:
            mail.outbox = []
            self.helper.handler.notify_email(template, 'Sample subject %s, %s')
            eq_(len(mail.outbox), 1)
            assert mail.outbox[0].body, 'Expected a message'

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

    def test_request_more_information(self):
        self.setup_data(amo.STATUS_PUBLIC, ['addon_files'])
        self.helper.handler.request_information()

        eq_(self.version.has_info_request, True)

        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject, self.preamble)

        eq_(self.check_log_count(amo.LOG.REQUEST_INFORMATION.id), 1)

    def test_email_no_locale(self):
        self.setup_data(amo.STATUS_NOMINATED, ['addon_files'])
        self.helper.handler.process_public()

        eq_(len(mail.outbox), 1)
        assert '/en-US/firefox/addon/a3615' not in mail.outbox[0].body
        assert '/addon/a3615' in mail.outbox[0].body

    def test_nomination_to_public_no_files(self):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status, ['addon_files'])
            self.helper.handler.process_public()

            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_PUBLIC)

    def test_nomination_to_public_and_current_version(self):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status, ['addon_files'])
            self.addon.update(_current_version=None)

            addon = Addon.objects.get(pk=3615)
            assert not addon.current_version
            self.helper.handler.process_public()
            assert addon.current_version

    def test_nomination_to_public_new_addon(self):
        """ Make sure new add-ons can be made public (bug 637959) """
        self.create_switch(name='reviewer-incentive-points')
        status = amo.STATUS_NOMINATED
        self.setup_data(status)

        # Make sure we have no public files
        for i in self.addon.versions.all():
            i.files.update(status=amo.STATUS_UNREVIEWED)

        self.helper.handler.process_public()

        # Re-fetch the add-on
        addon = Addon.objects.get(pk=3615)

        eq_(addon.status, amo.STATUS_PUBLIC)
        eq_(addon.highest_status, amo.STATUS_PUBLIC)

        eq_(addon.versions.all()[0].files.all()[0].status,
            amo.STATUS_PUBLIC)

        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject, '%s Fully Reviewed' % self.preamble)

        assert storage.exists(self.file.mirror_file_path)

        eq_(self.check_log_count(amo.LOG.APPROVE_VERSION.id), 1)

        self._check_score(amo.REVIEWED_ADDON_FULL)

    def test_nomination_to_public(self):
        self.create_switch(name='reviewer-incentive-points')
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_public()

            eq_(self.addon.status, amo.STATUS_PUBLIC)
            eq_(self.addon.highest_status, amo.STATUS_PUBLIC)
            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_PUBLIC)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Fully Reviewed' % self.preamble)

            assert storage.exists(self.file.mirror_file_path)

            eq_(self.check_log_count(amo.LOG.APPROVE_VERSION.id), 1)

            self._check_score(amo.REVIEWED_ADDON_FULL)

    def to_preliminary_premium(self, statuses):
        for type_ in amo.ADDON_PREMIUMS:
            self.addon.update(premium_type=type_)
            for status in helpers.NOMINATED_STATUSES:
                self.setup_data(status)
                self.assertRaises(AssertionError,
                                  self.helper.handler.process_preliminary)

    def test_nomination_to_preliminary_premium(self):
        self.to_preliminary_premium(helpers.NOMINATED_STATUSES)

    def test_nomination_to_preliminary(self):
        self.create_switch(name='reviewer-incentive-points')
        for status in helpers.NOMINATED_STATUSES:
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

            assert storage.exists(self.file.mirror_file_path)

            eq_(self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id), 1)

            self._check_score(amo.REVIEWED_ADDON_FULL)

    def test_nomination_to_sandbox(self):
        for status in helpers.NOMINATED_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            eq_(self.addon.highest_status, amo.STATUS_PUBLIC)
            eq_(self.addon.status, amo.STATUS_NULL)
            eq_(self.addon.versions.all()[0].files.all()[0].status,
                amo.STATUS_DISABLED)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Rejected' % self.preamble)

            assert not storage.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.REJECT_VERSION.id), 1)

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

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 2)
            eq_(mail.outbox[1].subject,
                'Super review requested: Delicious Bookmarks')
            eq_(mail.outbox[0].subject,
                ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
                 'Admin Review'))
            eq_(self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id), 1)

    def test_unreviewed_to_public(self):
        self.setup_data(amo.STATUS_UNREVIEWED)
        self.assertRaises(AssertionError,
                          self.helper.handler.process_public)

    def test_lite_to_public(self):
        self.setup_data(amo.STATUS_LITE)
        self.assertRaises(AssertionError,
                          self.helper.handler.process_public)

    def test_preliminary_to_preliminary_premium(self):
        self.to_preliminary_premium(helpers.PRELIMINARY_STATUSES)

    def test_preliminary_to_preliminary(self):
        self.create_switch(name='reviewer-incentive-points')
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_preliminary()

            for file in self.helper.handler.data['addon_files']:
                eq_(file.status, amo.STATUS_LITE)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject,
                '%s Preliminary Reviewed' % self.preamble)

            assert storage.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.PRELIMINARY_VERSION.id), 1)

            self._check_score(amo.REVIEWED_ADDON_PRELIM)

    def test_preliminary_to_sandbox(self):
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                eq_(file.status, amo.STATUS_DISABLED)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Rejected' % self.preamble)

            assert not storage.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.REJECT_VERSION.id), 1)

    def test_preliminary_upgrade_to_sandbox(self):
        self.setup_data(amo.STATUS_LITE)
        eq_(self.addon.status, amo.STATUS_LITE)
        eq_(self.file.status, amo.STATUS_LITE)

        a = create_addon_file(self.addon.name, '2.2', amo.STATUS_LITE,
                              amo.STATUS_UNREVIEWED)
        self.version = a['version']

        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.helper = self.get_helper()
        self.helper.set_data(self.get_data())

        self.helper.handler.process_sandbox()
        eq_(self.addon.status, amo.STATUS_LITE)
        eq_(self.file.status, amo.STATUS_LITE)
        f = File.objects.get(pk=a['file'].id)
        eq_(f.status, amo.STATUS_DISABLED)

    def test_preliminary_to_super_review(self):
        for status in helpers.PRELIMINARY_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 2)
            eq_(mail.outbox[1].subject,
                'Super review requested: Delicious Bookmarks')
            eq_(mail.outbox[0].subject,
                ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
                 'Admin Review'))
            eq_(self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id), 1)

    def test_nomination_to_super_review_and_escalate(self):
        # Note we are changing the file status here.
        for file_status in (amo.STATUS_PENDING, amo.STATUS_UNREVIEWED):
            self.setup_data(amo.STATUS_LITE)
            self.file.update(status=file_status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 2)
            eq_(mail.outbox[1].subject,
                'Super review requested: Delicious Bookmarks')
            eq_(mail.outbox[0].subject,
                ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
                 'Admin Review'))

            eq_(self.check_log_count(amo.LOG.REQUEST_SUPER_REVIEW.id), 1)

    def test_pending_to_public(self):
        self.create_switch(name='reviewer-incentive-points')
        for status in helpers.PENDING_STATUSES:
            self.setup_data(status)
            self.create_paths()
            self.helper.handler.process_public()

            for file in self.helper.handler.data['addon_files']:
                eq_(file.status, amo.STATUS_PUBLIC)

            eq_(len(mail.outbox), 1)
            eq_(mail.outbox[0].subject, '%s Fully Reviewed' % self.preamble)

            assert storage.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.APPROVE_VERSION.id), 1)

            if status == amo.STATUS_PUBLIC:
                self._check_score(amo.REVIEWED_ADDON_UPDATE)

    def test_pending_to_sandbox(self):
        for status in helpers.PENDING_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_sandbox()

            for file in self.helper.handler.data['addon_files']:
                eq_(file.status, amo.STATUS_DISABLED)

            eq_(len(mail.outbox), 1)
            assert 'did not meet the criteria' in mail.outbox[0].body

            assert not storage.exists(self.file.mirror_file_path)
            eq_(self.check_log_count(amo.LOG.REJECT_VERSION.id), 1)

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

        assert not 'Tested' in mail.outbox[0].body

    def test_pending_to_super_review(self):
        for status in helpers.PENDING_STATUSES:
            self.setup_data(status)
            self.helper.handler.process_super_review()

            eq_(self.addon.admin_review, True)

            eq_(len(mail.outbox), 2)
            eq_(mail.outbox[1].subject,
                'Super review requested: Delicious Bookmarks')
            eq_(mail.outbox[0].subject,
                ('Mozilla Add-ons: Delicious Bookmarks 2.1.072 flagged for '
                 'Admin Review'))

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
        for status in REVIEW_FILES_STATUSES:
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
    eq_(len(mail.outbox), 1)
    eq_(mail.outbox[0].body.count(s), len(ctx))


class TestCompareLink(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.current = File.objects.get(pk=67442)
        self.version = Version.objects.create(addon=self.addon)

    def test_same_platform(self):
        file = File.objects.create(version=self.version,
                                   platform=self.current.platform)
        eq_(file.pk, helpers.file_compare(self.current, self.version).pk)

    def test_different_platform(self):
        file = File.objects.create(version=self.version,
                                   platform=self.current.platform)
        File.objects.create(version=self.version,
                            platform_id=amo.PLATFORM_LINUX.id)
        eq_(file.pk, helpers.file_compare(self.current, self.version).pk)

    def test_specific_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()

        linux = File.objects.create(version=self.version,
                                    platform_id=amo.PLATFORM_LINUX.id)
        eq_(linux.pk, helpers.file_compare(self.current, self.version).pk)

    def test_no_platform(self):
        self.current.platform_id = amo.PLATFORM_LINUX.id
        self.current.save()
        file = File.objects.create(version=self.version,
                                   platform_id=amo.PLATFORM_WIN.id)
        eq_(file.pk, helpers.file_compare(self.current, self.version).pk)
