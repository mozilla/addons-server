# -*- coding: utf-8 -*-
import json

from elasticsearch_dsl import Search
from mock import Mock

from django.test.client import RequestFactory

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.search.filters import (
    PublicContentFilter, SearchQueryFilter, SortingFilter)


class FilterTestsBase(TestCase):
    # Base TestCase class - Does not need to inherit from ESTestCase as the
    # queries will never actually be executed.

    def setUp(self):
        super(FilterTestsBase, self).setUp()
        self.req = RequestFactory().get('/')
        self.view_class = Mock()

    def _filter(self, req=None, data=None):
        req = req or RequestFactory().get('/', data=data or {})
        queryset = Search()
        for filter_class in self.filter_classes:
            queryset = filter_class().filter_queryset(req, queryset,
                                                      self.view_class)
        return queryset.to_dict()


class TestQueryFilter(FilterTestsBase):

    filter_classes = [SearchQueryFilter]

    def test_q(self):
        qs = self._filter(data={'q': 'tea pot'})
        # Spot check a few queries.
        should = (qs['query']['function_score']['query']['bool']['should'])

        expected = {
            'match': {
                'name': {
                    'query': 'tea pot', 'boost': 4, 'slop': 1, 'type': 'phrase'
                }
            }
        }
        assert expected in should

        expected = {
            'prefix': {'name': {'boost': 1.5, 'value': 'tea pot'}}
        }
        assert expected in should

        expected = {
            'match': {
                'name_english': {
                    'query': 'tea pot', 'boost': 2.5,
                    'analyzer': 'english'
                }
            }
        }
        assert expected in should

        expected = {
            'match': {
                'description_english': {
                    'query': 'tea pot', 'boost': 0.6,
                    'analyzer': 'english', 'type': 'phrase'
                }
            }
        }
        assert expected in should

    def test_fuzzy_single_word(self):
        qs = self._filter(data={'q': 'blah'})
        should = (qs['query']['function_score']['query']['bool']['should'])
        expected = {
            'fuzzy': {
                'name': {
                    'boost': 2, 'prefix_length': 4, 'value': 'blah'
                }
            }
        }
        assert expected in should

    def test_no_fuzzy_multi_word(self):
        qs = self._filter(data={'q': 'search terms'})
        qs_str = json.dumps(qs)
        assert 'fuzzy' not in qs_str


class TestPublicContentFilter(FilterTestsBase):

    filter_classes = [PublicContentFilter]

    def test_status(self):
        qs = self._filter(self.req)
        must = qs['query']['filtered']['filter']['bool']['must']
        must_not = qs['query']['filtered']['filter']['bool']['must_not']

        assert {'term': {'status': amo.REVIEWED_STATUSES}} in must
        assert {'term': {'is_disabled': True}} in must_not
        assert {'term': {'is_deleted': True}} in must_not
        assert {'term': {'is_listed': False}} in must_not


class TestSortingFilter(FilterTestsBase):

    filter_classes = [SortingFilter]

    def _reformat_order(self, key):
        # elasticsearch-dsl transforms '-something' for us, so we have to
        # expect the sort param in this format when we inspect the resulting
        # queryset object.
        return {key[1:]: {'order': 'desc'}} if key.startswith('-') else key

    def test_sort_default(self):
        qs = self._filter(data={'q': 'something'})
        assert 'sort' not in qs

        qs = self._filter()
        assert qs['sort'] == [self._reformat_order('-weekly_downloads')]

    def test_sort_query(self):
        SORTING_PARAMS = SortingFilter.SORTING_PARAMS

        for param in SORTING_PARAMS:
            qs = self._filter(data={'sort': param})
            assert qs['sort'] == [self._reformat_order(SORTING_PARAMS[param])]
        # Having a search query does not change anything, the requested sort
        # takes precedence.
        for param in SORTING_PARAMS:
            qs = self._filter(data={'q': 'something', 'sort': param})
            assert qs['sort'] == [self._reformat_order(SORTING_PARAMS[param])]

        # If the sort query is wrong, just omit it and fall back to the
        # default.
        qs = self._filter(data={'sort': 'WRONGLOL'})
        assert qs['sort'] == [self._reformat_order('-weekly_downloads')]

        # Same as above but with a search query.
        qs = self._filter(data={'q': 'something', 'sort': 'WRONGLOL'})
        assert 'sort' not in qs

    def test_sort_query_multiple(self):
        qs = self._filter(data={'sort': ['rating,created']})
        assert qs['sort'] == [self._reformat_order('-bayesian_rating'),
                              self._reformat_order('-created')]

        # If the sort query is wrong, just omit it.
        qs = self._filter(data={'sort': ['LOLWRONG,created']})
        assert qs['sort'] == [self._reformat_order('-created')]


class TestCombinedFilter(FilterTestsBase):
    """
    Basic test to ensure that when filters are combined they result in the
    expected query structure.

    """
    filter_classes = [SearchQueryFilter, PublicContentFilter, SortingFilter]

    def test_combined(self):
        qs = self._filter(data={'q': 'test'})
        filtered = qs['query']['filtered']
        assert filtered['query']['function_score']
        assert filtered['filter']

        must = filtered['filter']['bool']['must']
        assert {'term': {'status': amo.REVIEWED_STATUSES}} in must

        must_not = filtered['filter']['bool']['must_not']
        assert {'term': {'is_disabled': True}} in must_not

        assert 'sort' not in qs

        should = filtered['query']['function_score']['query']['bool']['should']
        expected = {
            'match': {
                'name_english': {
                    'analyzer': 'english', 'boost': 2.5, 'query': u'test'
                }
            }
        }
        assert expected in should
