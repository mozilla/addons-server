from unittest.mock import MagicMock, Mock

from django.core.paginator import EmptyPage, InvalidPage, PageNotAnInteger, Paginator

import pytest

from olympia.amo.pagination import ESPaginator
from olympia.amo.templatetags.jinja_helpers import PaginationRenderer
from olympia.amo.tests import TestCase


def mock_pager(page_number, num_pages, count):
    m = Mock()
    m.paginator = Mock()
    m.number = page_number
    m.paginator.num_pages = num_pages
    m.paginator.count = count
    return m


def assert_range(page_number, num_pages, expected):
    p = PaginationRenderer(mock_pager(page_number, num_pages, 100))
    assert list(p.range()) == expected


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
        mocked_qs.__len__.return_value = 42
        paginator = Paginator(mocked_qs, 5)
        # With the base paginator, requesting any page forces a count.
        paginator.page(1)
        assert paginator.count == 42
        assert mocked_qs.count.call_count + mocked_qs.__len__.call_count == 1

        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 666
        paginator = ESPaginator(mocked_qs, 5)
        # With the ES paginator, the count is fetched from the 'total' key
        # in the results.
        paginator.page(1)
        assert paginator.count == 666
        assert mocked_qs.count.call_count == 0

    def test_invalid_page(self):
        total = 50000
        page_size = 5
        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = total
        paginator = ESPaginator(mocked_qs, page_size)

        assert ESPaginator.max_result_window == 30000

        with pytest.raises(InvalidPage) as exc:
            paginator.page(ESPaginator.max_result_window / page_size + 1)

        # Make sure we raise exactly `InvalidPage`, this is needed
        # unfortunately since `pytest.raises` won't check the exact
        # instance but also accepts parent exceptions inherited.
        assert (
            str(exc.value) == 'That page number is too high for the current page size'
        )
        assert isinstance(exc.value, InvalidPage)

        with self.assertRaises(EmptyPage):
            paginator.page(0)

        with self.assertRaises(PageNotAnInteger):
            paginator.page('lol')

    def test_no_pages_beyond_max_window_result(self):
        total = 50000
        page_size = 5
        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = total
        paginator = ESPaginator(mocked_qs, page_size)

        assert ESPaginator.max_result_window == 30000

        page = paginator.page(ESPaginator.max_result_window / page_size - 1)
        assert page.has_next() is True

        page = paginator.page(ESPaginator.max_result_window / page_size)
        assert page.has_next() is False
