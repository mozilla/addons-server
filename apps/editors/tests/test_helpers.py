# -*- coding: utf8 -*-

import os

from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse
from editors.helpers import ViewPendingQueueTable, ViewFullReviewQueueTable

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
