from django.core.paginator import (
    EmptyPage, InvalidPage, PageNotAnInteger, Paginator)

import pytest

from mock import MagicMock, Mock

from olympia.addons.models import Addon
from olympia.amo.pagination import ESPaginator
from olympia.amo.templatetags.jinja_helpers import PaginationRenderer
from olympia.amo.tests import TestCase, ESTestCase, addon_factory
from olympia.amo.utils import paginate


pytestmark = pytest.mark.django_db


def mock_pager(page_number, num_pages, count):
    m = Mock()
    m.paginator = Mock()
    m.number = page_number
    m.paginator.num_pages = num_pages
    m.paginator.count = count
    return m


def assert_range(page_number, num_pages, expected):
    p = PaginationRenderer(mock_pager(page_number, num_pages, 100))
    assert p.range() == expected


def test_page_range():
    assert_range(1, 75, [1, 2, 3, 4, 5, 6, 7, 8])
    assert_range(2, 75, [1, 2, 3, 4, 5, 6, 7, 8])
    assert_range(3, 75, [1, 2, 3, 4, 5, 6, 7, 8])
    assert_range(4, 75, [1, 2, 3, 4, 5, 6, 7, 8])
    assert_range(5, 75, [2, 3, 4, 5, 6, 7, 8])
    assert_range(6, 75, [3, 4, 5, 6, 7, 8, 9])
    assert_range(8, 75, [5, 6, 7, 8, 9, 10, 11])

    assert_range(37, 75, [34, 35, 36, 37, 38, 39, 40])

    assert_range(70, 75, [67, 68, 69, 70, 71, 72, 73])
    assert_range(71, 75, [68, 69, 70, 71, 72, 73, 74])
    assert_range(72, 75, [68, 69, 70, 71, 72, 73, 74, 75])
    assert_range(73, 75, [68, 69, 70, 71, 72, 73, 74, 75])
    assert_range(74, 75, [68, 69, 70, 71, 72, 73, 74, 75])
    assert_range(75, 75, [68, 69, 70, 71, 72, 73, 74, 75])

    assert_range(1, 8, [1, 2, 3, 4, 5, 6, 7, 8])


def test_dots():
    p = PaginationRenderer(mock_pager(1, 5, 100))
    assert not p.pager.dotted_upper
    assert not p.pager.dotted_lower

    p = PaginationRenderer(mock_pager(1, 25, 100))
    assert p.pager.dotted_upper
    assert not p.pager.dotted_lower

    p = PaginationRenderer(mock_pager(12, 25, 100))
    assert p.pager.dotted_upper
    assert p.pager.dotted_lower

    p = PaginationRenderer(mock_pager(24, 25, 100))
    assert not p.pager.dotted_upper
    assert p.pager.dotted_lower


class TestSearchPaginator(TestCase):

    def test_single_hit(self):
        """Test the ESPaginator only queries ES one time."""
        mocked_qs = MagicMock()
        mocked_qs.count.return_value = 42
        paginator = Paginator(mocked_qs, 5)
        # With the base paginator, requesting any page forces a count.
        paginator.page(1)
        assert paginator.count == 42
        assert mocked_qs.count.call_count == 1

        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 666
        paginator = ESPaginator(mocked_qs, 5)
        # With the ES paginator, the count is fetched from the 'total' key
        # in the results.
        paginator.page(1)
        assert paginator.count == 666
        assert mocked_qs.count.call_count == 0

    def test_invalid_page(self):
        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 30000
        paginator = ESPaginator(mocked_qs, 5)

        assert ESPaginator.max_result_window == 25000

        with pytest.raises(InvalidPage) as exc:
            # We're fetching 5 items per page, so requesting page 5001 should
            # fail, since the max result window should is set to 25000.
            paginator.page(5000 + 1)

        # Make sure we raise exactly `InvalidPage`, this is needed
        # unfortunately since `pytest.raises` won't check the exact
        # instance but also accepts parent exceptions inherited.
        assert (
            exc.value.message ==
            'That page number is too high for the current page size')
        assert isinstance(exc.value, InvalidPage)

        with self.assertRaises(EmptyPage):
            paginator.page(0)

        with self.assertRaises(PageNotAnInteger):
            paginator.page('lol')

    def test_no_pages_beyond_max_window_result(self):
        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 30000
        paginator = ESPaginator(mocked_qs, 5)

        assert ESPaginator.max_result_window == 25000

        page = paginator.page(4999)
        assert page.has_next() is True

        page = paginator.page(5000)
        assert page.has_next() is False

    def test_paginate_returns_this_paginator(self):
        request = MagicMock()
        request.GET.get.return_value = 1
        request.GET.urlencode.return_value = ''
        request.path = ''

        qs = Addon.search()
        pager = paginate(request, qs)
        assert isinstance(pager.paginator, ESPaginator)


class TestNonDSLMode(ESTestCase):

    def test_count_non_dsl_mode(self):
        addon_factory()
        addon_factory()
        addon_factory()

        self.refresh()

        p = ESPaginator(Addon.search(), 20, use_elasticsearch_dsl=False)

        assert p.count == 3

        p.page(1)

        assert p.count == 3
        assert p.count == Addon.search().count()
