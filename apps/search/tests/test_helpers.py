from django.utils import translation

import jingo
from mock import Mock
from nose.tools import eq_

from amo.tests.test_helpers import render


def test_showing_helper():
    translation.activate('en-US')
    tpl = "{{ showing(query, tag, pager) }}"
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 1000
    c = {}
    c['query'] = ''
    c['tag'] = ''
    c['pager'] = pager
    eq_('Showing 1 - 20 of 1000 results', render(tpl, c))
    c['tag'] = 'foo'
    eq_('Showing 1 - 20 of 1000 results tagged with <strong>foo</strong>',
            render(tpl, c))
    c['query'] = 'balls'
    eq_('Showing 1 - 20 of 1000 results for <strong>balls</strong> '
        'tagged with <strong>foo</strong>', render(tpl, c))
    c['tag'] = ''
    eq_('Showing 1 - 20 of 1000 results for <strong>balls</strong>',
        render(tpl, c))


def test_pagination_result_count():
    jingo.load_helpers()
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 999
    c = dict(pager=pager)
    eq_(u'Results <strong>1</strong>-<strong>20</strong> of '
        '<strong>999</strong>',
        render("{{ pagination_result_count(pager) }}", c))
