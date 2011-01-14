# -*- coding: utf8 -*-

import os

from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse
from editors.helpers import ViewEditorQueueTable

class TestViewEditorQueueTable(test_utils.TestCase):

    def setUp(self):
        super(TestViewEditorQueueTable, self).setUp()
        qs = Mock()
        self.table = ViewEditorQueueTable(qs)

    def test_addon_name(self):
        row = Mock()
        row.addon_name = 'フォクすけといっしょ 0.12'.decode('utf8')
        row.version_id = 1234
        a = pq(self.table.render_addon_name(row))
        eq_(a.attr('href'),
            reverse('editors.review', args=[row.version_id]))
        eq_(a.text(), row.addon_name)

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
        row.platform_id = amo.PLATFORM_LINUX.id
        eq_(self.table.render_additional_info(row), u'Linux only')

    def test_additional_info_for_all_platforms(self):
        row = Mock()
        row.is_site_specific = False
        row.platform_id = amo.PLATFORM_ALL.id
        eq_(self.table.render_additional_info(row), u'')

    def test_applications(self):
        row = Mock()
        row.applications = ','.join([str(amo.FIREFOX.id),
                                     str(amo.THUNDERBIRD.id)])
        doc = pq(self.table.render_applications(row))
        eq_(sorted(a.attrib['class'] for a in doc('div div')),
            ['app-icon ed-sprite-firefox', 'app-icon ed-sprite-thunderbird'])

    def test_waiting_time_in_days(self):
        row = Mock()
        row.days_since_created = 10
        row.hours_since_created = 10 * 24
        eq_(self.table.render_days_since_created(row), u'10 days')

    def test_waiting_time_in_hours(self):
        row = Mock()
        row.days_since_created = 1
        row.hours_since_created = 22
        eq_(self.table.render_days_since_created(row), u'22 hours')

    def test_flags_admin_review(self):
        row = Mock()
        row.admin_review = True
        doc = pq(self.table.render_flags(row))
        eq_(doc('div').attr('class'), 'app-icon ed-sprite-admin-review')

    def test_no_flags(self):
        row = Mock()
        row.admin_review = False
        eq_(self.table.render_flags(row), '')
