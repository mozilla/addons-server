from django.utils import translation

import jingo
import pytest
from mock import Mock

from amo.tests.test_helpers import render


pytestmark = pytest.mark.django_db


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
    assert 'Showing 1 - 20 of 1000 results' == render(tpl, c)
    c['tag'] = 'foo'
    assert 'Showing 1 - 20 of 1000 results tagged with <strong>foo</strong>' == render(tpl, c)
    c['query'] = 'balls'
    assert 'Showing 1 - 20 of 1000 results for <strong>balls</strong> ' 'tagged with <strong>foo</strong>' == render(tpl, c)
    c['tag'] = ''
    assert 'Showing 1 - 20 of 1000 results for <strong>balls</strong>' == render(tpl, c)


def test_pagination_result_count():
    jingo.load_helpers()
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 999
    c = dict(pager=pager)
    assert u'Results <strong>1</strong>-<strong>20</strong> of ' '<strong>999</strong>' == render("{{ pagination_result_count(pager) }}", c)
