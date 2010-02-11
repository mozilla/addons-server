from mock import Mock
from nose.tools import eq_

from amo.helpers import Paginator


def mock_pager(page_number, num_pages, count):
    m = Mock()
    m.paginator = Mock()
    m.number = page_number
    m.paginator.num_pages = num_pages
    m.paginator.count = count
    return m


def assert_range(page_number, num_pages, expected):
    p = Paginator(mock_pager(page_number, num_pages, 100))
    eq_(p.range(), expected)


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
    p = Paginator(mock_pager(1, 5, 100))
    assert not p.pager.dotted_upper
    assert not p.pager.dotted_lower

    p = Paginator(mock_pager(1, 25, 100))
    assert p.pager.dotted_upper
    assert not p.pager.dotted_lower

    p = Paginator(mock_pager(12, 25, 100))
    assert p.pager.dotted_upper
    assert p.pager.dotted_lower

    p = Paginator(mock_pager(24, 25, 100))
    assert not p.pager.dotted_upper
    assert p.pager.dotted_lower
