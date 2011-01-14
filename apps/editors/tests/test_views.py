# -*- coding: utf8 -*-
import re

from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse


class EditorTest(test_utils.TestCase):

    def login_as_editor(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

class TestPendingQueue(EditorTest):
    fixtures = ['base/users', 'editors/pending-queue']

    def setUp(self):
        super(TestPendingQueue, self).setUp()
        self.login_as_editor()

    def test_only_viewable_by_editor(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 403)

    def test_grid(self):
        r = self.client.get(reverse('editors.queue_pending'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('div.section table tr th:eq(0)').text(), u'Addon')
        eq_(doc('div.section table tr th:eq(1)').text(), u'Type')
        eq_(doc('div.section table tr th:eq(2)').text(), u'Waiting Time')
        eq_(doc('div.section table tr th:eq(3)').text(), u'Applications')
        eq_(doc('div.section table tr th:eq(4)').text(), u'Flags')
        eq_(doc('div.section table tr th:eq(5)').text(),
            u'Additional Information')
        # Smoke test the grid. More tests in test_helpers.py
        eq_(doc('div.section table tr td:eq(0)').text(), u'Converter 1.0.0')
        eq_(doc('div.section table tr td a:eq(0)').attr('href'),
            reverse('editors.review', args=['118409']))
