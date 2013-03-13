# -*- coding: utf8 -*-
import amo.tests

from mkt.reviewers.utils import create_sort_link


class TestCreateSortLink(amo.tests.TestCase):
    """Test that the sortable table headers' have URLs created correctly."""

    def test_sort_asc_created(self):
        """
        Test that name's link sorts by asc if already sorting by created.
        """
        link = create_sort_link('Name', 'name', [('text_query', 'irrel')],
                                'created', 'desc')
        assert 'sort=name' in link
        assert 'order=asc' in link
        assert 'text_query=irrel' in link

    def test_sort_invert_created(self):
        """
        Test that created's link inverts order if already sorting by created.
        """
        link = create_sort_link('Waiting Time', 'created',
                                [('text_query', 'guybrush')], 'created',
                                'asc')
        assert 'sort=created' in link
        assert 'order=desc' in link
        assert 'text_query=guybrush' in link
        link = create_sort_link('Waiting Time', 'created', [], 'created',
                                'desc')
        assert 'order=asc' in link

    def test_no_xss(self):
        link = create_sort_link('Waiting Time', 'created',
                                [('script', '<script>alert("BIB");</script>')],
                                'created', 'asc')
        assert '<script>' not in link

    def test_unicode(self):
        link = create_sort_link('Name', 'name', [('text_query', 'Feliz Año')],
                                'created', 'desc')
        assert 'sort=name' in link
        assert 'order=asc' in link
        assert 'text_query=Feliz+A%C3%B1o' in link
