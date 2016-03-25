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

    def test_sort(self):
        qs = self._filter(data={'q': 'something'})
        assert 'sort' not in qs
        qs = self._filter()
        assert qs['sort'] == ['name_sort']


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
