# -*- coding: utf-8 -*-
import copy

from unittest.mock import Mock, patch

from django.test.client import RequestFactory
from django.utils import translation

from elasticsearch_dsl import Search
from rest_framework import serializers

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.constants.categories import CATEGORIES
from olympia.search.filters import (
    ReviewedContentFilter, SearchParameterFilter, SearchQueryFilter,
    SortingFilter)


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

    def _test_q(self, qs):
        # Spot check a few queries.
        should = qs['query']['function_score']['query']['bool']['should']

        expected = {
            'match_phrase': {
                'name': {
                    'query': 'tea pot', 'boost': 8.0, 'slop': 1,
                    '_name': 'MatchPhrase(name)',
                }
            }
        }
        assert expected in should

        expected = {
            'prefix': {
                'name': {
                    'boost': 3.0, 'value': 'tea pot',
                    '_name': 'Prefix(name)',
                }
            }
        }
        assert expected in should

        expected = {
            'match': {
                'name_l10n_english': {
                    'query': 'tea pot', 'boost': 5.0,
                    'analyzer': 'english',
                    'operator': 'and',
                    '_name': 'Match(name_l10n_english)',
                }
            }
        }
        assert expected in should

        expected = {
            'multi_match': {
                '_name': (
                    'MultiMatch(Match(summary),Match(summary_l10n_english))'),
                'query': 'tea pot',
                'operator': 'and',
                'fields': ['summary', 'summary_l10n_english'],
                'boost': 3.0,
            }
        }
        assert expected in should

        expected = {
            'multi_match': {
                '_name': (
                    'MultiMatch(Match(description),'
                    'Match(description_l10n_english))'),
                'query': 'tea pot',
                'operator': 'and',
                'fields': ['description', 'description_l10n_english'],
                'boost': 2.0,
            }
        }
        assert expected in should

        functions = qs['query']['function_score']['functions']
        assert len(functions) == 3
        assert functions[0] == {
            'field_value_factor': {
                'field': 'average_daily_users', 'modifier': 'log2p'
            }
        }
        assert functions[1] == {
            'filter': {
                'bool': {
                    'must': [
                        {'term': {'is_experimental': False}},
                        {'terms': {'status': (4,)}},
                        {'exists': {'field': 'current_version'}},
                        {'term': {'is_disabled': False}}
                    ]
                }
            },
            'weight': 4.0
        }
        assert functions[2] == {
            'filter': {
                'term': {'is_recommended': True}},
            'weight': 5.0}
        return qs

    def test_no_rescore_if_not_sorting_by_relevance(self):
        qs = self._test_q(
            self._filter(data={'q': 'tea pot', 'sort': 'rating'}))
        assert 'rescore' not in qs

    def test_q(self):
        qs = self._test_q(self._filter(data={'q': 'tea pot'}))

        expected_rescore = {
            'bool': {
                'should': [
                    {
                        'multi_match': {
                            '_name': (
                                'MultiMatch(MatchPhrase(summary),'
                                'MatchPhrase(summary_l10n_english))'),
                            'query': 'tea pot',
                            'slop': 10,
                            'type': 'phrase',
                            'fields': ['summary', 'summary_l10n_english'],
                            'boost': 3.0,
                        },
                    },
                    {
                        'multi_match': {
                            '_name': (
                                'MultiMatch(MatchPhrase(description),'
                                'MatchPhrase(description_l10n_english))'),
                            'query': 'tea pot',
                            'slop': 10,
                            'type': 'phrase',
                            'fields': ['description',
                                       'description_l10n_english'],
                            'boost': 2.0,
                        },
                    }
                ]
            }
        }

        assert qs['rescore'] == {
            'window_size': 10,
            'query': {
                'rescore_query': expected_rescore
            }
        }

    def test_q_too_long(self):
        with self.assertRaises(serializers.ValidationError):
            self._filter(data={'q': 'a' * 101})

    def test_fuzzy_single_word(self):
        qs = self._filter(data={'q': 'blah'})
        should = qs['query']['function_score']['query']['bool']['should']
        expected = {
            'dis_max': {
                'queries': [
                    {
                        'match': {
                            'name': {
                                'prefix_length': 2,
                                'query': 'blah',
                                'fuzziness': 'AUTO',
                                'minimum_should_match': '2<2 3<-25%',
                            }
                        }
                    },
                    {
                        'match': {
                            'name.trigrams': {
                                'query': 'blah',
                                'minimum_should_match': '66%',
                            }
                        }
                    },
                ],
                'boost': 4.0,
                '_name': 'DisMax(FuzzyMatch(name), Match(name.trigrams))'
            }
        }
        assert expected in should

    def test_fuzzy_multi_word(self):
        qs = self._filter(data={'q': 'search terms'})
        should = qs['query']['function_score']['query']['bool']['should']
        expected = {
            'dis_max': {
                'queries': [
                    {
                        'match': {
                            'name': {
                                'prefix_length': 2,
                                'query': 'search terms',
                                'fuzziness': 'AUTO',
                                'minimum_should_match': '2<2 3<-25%',
                            }
                        }
                    },
                    {
                        'match': {
                            'name.trigrams': {
                                'query': 'search terms',
                                'minimum_should_match': '66%',
                            }
                        }
                    },
                ],
                'boost': 4.0,
                '_name': 'DisMax(FuzzyMatch(name), Match(name.trigrams))'
            }
        }
        assert expected in should

    def test_no_fuzzy_if_query_too_long(self):
        def do_test():
            qs = self._filter(data={'q': 'this search query is too long.'})
            should = qs['query']['function_score']['query']['bool']['should']
            return should

        # Make sure there is no fuzzy clause (the search query is too long).
        should = do_test()
        expected = {
            'dis_max': {
                'queries': [
                    {
                        'match': {
                            'name': {
                                'prefix_length': 2,
                                'query': 'this search query is too long.',
                                'fuzziness': 'AUTO',
                                'minimum_should_match': '2<2 3<-25%',
                            }
                        }
                    },
                    {
                        'match': {
                            'name.trigrams': {
                                'query': 'this search query is too long.',
                                'minimum_should_match': '66%',
                            }
                        }
                    },
                ],
                'boost': 4.0,
                '_name': 'DisMax(FuzzyMatch(name), Match(name.trigrams))'
            }
        }
        assert expected not in should

        # Re-do the same test but mocking the limit to a higher value, the
        # fuzzy query should be present.
        with patch.object(
                SearchQueryFilter, 'MAX_QUERY_LENGTH_FOR_FUZZY_SEARCH', 100):
            should = do_test()
            assert expected in should

    def test_q_exact(self):
        qs = self._filter(data={'q': 'Adblock Plus'})
        should = qs['query']['function_score']['query']['bool']['should']

        expected = {
            'dis_max': {
                'queries': [
                    {'term': {'name.raw': u'adblock plus'}},
                    {'term': {'name_l10n_english.raw': u'adblock plus'}},
                ],
                'boost': 100.0,
                '_name': 'DisMax(Term(name.raw), Term(name_l10n_english.raw))'
            }
        }

        assert expected in should

        # In a language we don't have a language-specific analyzer for, it
        # should fall back to the "name.raw" field that uses the default locale
        # translation.
        with translation.override('mn'):
            qs = self._filter(data={'q': 'Adblock Plus'})
        should = qs['query']['function_score']['query']['bool']['should']

        expected = {
            'term': {
                'name.raw': {
                    'boost': 100, 'value': u'adblock plus',
                    '_name': 'Term(name.raw)'
                }
            }
        }

        assert expected in should


class TestReviewedContentFilter(FilterTestsBase):

    filter_classes = [ReviewedContentFilter]

    def test_status(self):
        qs = self._filter(self.req)
        assert 'must' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']

        assert {'terms': {'status': amo.REVIEWED_STATUSES}} in filter_
        assert {'exists': {'field': 'current_version'}} in filter_
        assert {'term': {'is_disabled': False}} in filter_


class TestSortingFilter(FilterTestsBase):

    filter_classes = [SortingFilter]

    def _reformat_order(self, key):
        # elasticsearch-dsl transforms '-something' for us, so we have to
        # expect the sort param in this format when we inspect the resulting
        # queryset object.
        return {key[1:]: {'order': 'desc'}} if key.startswith('-') else key

    def test_sort_default(self):
        qs = self._filter(data={'q': 'something'})
        assert qs['sort'] == [self._reformat_order('_score')]

        qs = self._filter()
        assert qs['sort'] == [
            self._reformat_order('-is_recommended'),
            self._reformat_order('-average_daily_users')]

    def test_sort_query(self):
        SORTING_PARAMS = copy.copy(SortingFilter.SORTING_PARAMS)
        SORTING_PARAMS.pop('random')  # Tested separately below.
        SORTING_PARAMS.pop('recommended')  # Tested separately below.

        for param, es in SORTING_PARAMS.items():
            qs = self._filter(data={'sort': param})
            if param == 'relevance':
                # relevance without q is ignored so default sort is used
                expected = [
                    self._reformat_order('-is_recommended'),
                    self._reformat_order('-average_daily_users')
                ]
            else:
                expected = [self._reformat_order(es)]
            assert qs['sort'] == expected
        # Having a search query does not change anything, the requested sort
        # takes precedence.
        for param in SORTING_PARAMS:
            qs = self._filter(data={'q': 'something', 'sort': param})
            assert qs['sort'] == [self._reformat_order(SORTING_PARAMS[param])]

        # If the sort query is wrong.
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'sort': 'WRONGLOL'})
        assert context.exception.detail == ['Invalid "sort" parameter.']

        # Same as above but with a search query.
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'q': 'something', 'sort': 'WRONGLOL'})
        assert context.exception.detail == ['Invalid "sort" parameter.']

    def test_sort_query_multiple(self):
        qs = self._filter(data={'sort': ['rating,created']})
        assert qs['sort'] == [self._reformat_order('-bayesian_rating'),
                              self._reformat_order('-created')]

        qs = self._filter(data={'sort': 'created,rating'})
        assert qs['sort'] == [self._reformat_order('-created'),
                              self._reformat_order('-bayesian_rating')]

        # If the sort query is wrong.
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'sort': ['LOLWRONG,created']})
        assert context.exception.detail == ['Invalid "sort" parameter.']

    def test_cant_combine_sorts_with_random(self):
        expected = 'The "random" "sort" parameter can not be combined.'

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'sort': ['rating,random']})
        assert context.exception.detail == [expected]

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'sort': 'random,created'})
        assert context.exception.detail == [expected]

    def test_sort_random_restrictions(self):
        expected = ('The "sort" parameter "random" can only be specified when '
                    'the "featured" or "recommended" parameter is also '
                    'present, and the "q" parameter absent.')

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'q': 'something', 'sort': 'random'})
        assert context.exception.detail == [expected]

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(
                data={'q': 'something', 'featured': 'true', 'sort': 'random'})
        assert context.exception.detail == [expected]

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(
                data={'q': 'something', 'recommended': 'true',
                      'sort': 'random'})
        assert context.exception.detail == [expected]

    def test_sort_random_featured(self):
        qs = self._filter(data={'featured': 'true', 'sort': 'random'})
        # Note: this test does not call AddonFeaturedQueryParam so it won't
        # apply the featured filtering. That's tested below in
        # TestCombinedFilter.test_filter_featured_sort_random
        assert qs['sort'] == ['_score']
        assert qs['query']['function_score']['functions'] == [
            {'random_score': {}}
        ]

    def test_sort_random(self):
        qs = self._filter(data={'recommended': 'true', 'sort': 'random'})
        # Note: this test does not call AddonRecommendedQueryParam so it won't
        # apply the recommended filtering. That's tested below in
        # TestCombinedFilter.test_filter_recommended_sort_random
        assert qs['sort'] == ['_score']
        assert qs['query']['function_score']['functions'] == [
            {'random_score': {}}
        ]

    def test_sort_recommended_only(self):
        # If you try to sort by just recommended it gets ignored
        qs = self._filter(data={'q': 'something', 'sort': 'recommended'})
        assert qs['sort'] == [self._reformat_order('_score')]

        qs = self._filter(data={'sort': 'recommended'})
        assert qs['sort'] == [
            self._reformat_order('-is_recommended'),
            self._reformat_order('-average_daily_users')]

    def test_sort_recommended_and_relevance(self):
        # with a q, recommended with relevance sort, recommended is ignored.
        qs = self._filter(
            data={'q': 'something', 'sort': 'recommended,relevance'})
        assert qs['sort'] == [self._reformat_order('_score')]

        # except if you don't specify a query, then it falls back to default
        qs = self._filter(data={'sort': 'recommended,relevance'})
        assert qs['sort'] == [
            self._reformat_order('-is_recommended'),
            self._reformat_order('-average_daily_users')]


class TestSearchParameterFilter(FilterTestsBase):
    filter_classes = [SearchParameterFilter]

    def test_search_by_type_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(
                data={'type': str(amo.ADDON_EXTENSION + 666)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'type': 'nosuchtype'})
        assert context.exception.detail == ['Invalid "type" parameter.']

    def test_search_by_type_id(self):
        qs = self._filter(data={'type': str(amo.ADDON_EXTENSION)})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'type': [amo.ADDON_EXTENSION]}} in filter_

        qs = self._filter(data={'type': str(amo.ADDON_STATICTHEME)})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'type': [amo.ADDON_STATICTHEME]}} in filter_

    def test_search_by_type_string(self):
        qs = self._filter(data={'type': 'extension'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'type': [amo.ADDON_EXTENSION]}} in filter_

        qs = self._filter(data={'type': 'statictheme'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'type': [amo.ADDON_STATICTHEME]}} in filter_

        qs = self._filter(data={'type': 'statictheme,extension'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert (
            {'terms': {'type': [amo.ADDON_STATICTHEME, amo.ADDON_EXTENSION]}}
            in filter_)

    def test_search_by_app_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'app': str(amo.FIREFOX.id + 666)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'app': 'nosuchapp'})
        assert context.exception.detail == ['Invalid "app" parameter.']

    def test_search_by_app_id(self):
        qs = self._filter(data={'app': str(amo.FIREFOX.id)})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'app': amo.FIREFOX.id}} in filter_

        qs = self._filter(data={'app': str(amo.ANDROID.id)})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'app': amo.ANDROID.id}} in filter_

    def test_search_by_app_string(self):
        qs = self._filter(data={'app': 'firefox'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'app': amo.FIREFOX.id}} in filter_

        qs = self._filter(data={'app': 'android'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'app': amo.ANDROID.id}} in filter_

    def test_search_by_appversion_app_missing(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'appversion': '46.0'})
        assert context.exception.detail == ['Invalid "app" parameter.']

    def test_search_by_appversion_app_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'appversion': '46.0',
                               'app': 'internet_explorer'})
        assert context.exception.detail == ['Invalid "app" parameter.']

    def test_search_by_appversion_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'appversion': 'not_a_version',
                               'app': 'firefox'})
        assert context.exception.detail == ['Invalid "appversion" parameter.']

    def test_search_by_appversion(self):
        qs = self._filter(data={'appversion': '46.0',
                                'app': 'firefox'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'app': amo.FIREFOX.id}} in filter_
        assert {'range': {'current_version.compatible_apps.1.min':
                {'lte': 46000000200100}}} in filter_
        assert {'range': {'current_version.compatible_apps.1.max':
                {'gte': 46000000000100}}} in filter_

    def test_search_by_platform_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(
                data={'platform': str(amo.PLATFORM_WIN.id + 42)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'platform': 'nosuchplatform'})
        assert context.exception.detail == ['Invalid "platform" parameter.']

    def test_search_by_platform_id(self):
        qs = self._filter(
            data={'platform': str(amo.PLATFORM_WIN.id)})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_WIN.id, amo.PLATFORM_ALL.id]}} in filter_

        qs = self._filter(
            data={'platform': str(amo.PLATFORM_LINUX.id)})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_LINUX.id, amo.PLATFORM_ALL.id]}} in filter_

    def test_search_by_platform_string(self):
        qs = self._filter(data={'platform': 'windows'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_WIN.id, amo.PLATFORM_ALL.id]}} in filter_

        qs = self._filter(data={'platform': 'win'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_WIN.id, amo.PLATFORM_ALL.id]}} in filter_

        qs = self._filter(data={'platform': 'darwin'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_MAC.id, amo.PLATFORM_ALL.id]}} in filter_

        qs = self._filter(data={'platform': 'mac'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_MAC.id, amo.PLATFORM_ALL.id]}} in filter_

        qs = self._filter(data={'platform': 'macosx'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_MAC.id, amo.PLATFORM_ALL.id]}} in filter_

        qs = self._filter(data={'platform': 'linux'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'platforms': [
            amo.PLATFORM_LINUX.id, amo.PLATFORM_ALL.id]}} in filter_

    def test_search_by_category_slug_no_app_or_type(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'category': 'other'})
        assert context.exception.detail == ['Invalid "app" parameter.']

    def test_search_by_category_id_no_app_or_type(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'category': 1})
        assert context.exception.detail == ['Invalid "app" parameter.']

    def test_search_by_category_slug(self):
        category = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['other']
        qs = self._filter(data={
            'category': 'other',
            'app': 'firefox',
            'type': 'extension'
        })
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'category': [category.id]}} in filter_

    def test_search_by_category_slug_multiple_types(self):
        category_a = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['other']
        category_b = CATEGORIES[amo.FIREFOX.id][amo.ADDON_STATICTHEME]['other']
        qs = self._filter(data={
            'category': 'other',
            'app': 'firefox',
            'type': 'extension,statictheme'
        })
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert (
            {'terms': {'category': [category_a.id, category_b.id]}} in filter_)

    def test_search_by_category_id(self):
        qs = self._filter(data={
            'category': 1,
            'app': 'firefox',
            'type': 'extension'
        })
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'terms': {'category': [1]}} in filter_

    def test_search_by_category_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(
                data={'category': 666, 'app': 'firefox', 'type': 'extension'})
        assert context.exception.detail == ['Invalid "category" parameter.']

    def test_search_by_tag(self):
        qs = self._filter(data={'tag': 'foo'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'tags': 'foo'}} in filter_

        qs = self._filter(data={'tag': 'foo,bar'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'tags': 'foo'}} in filter_
        assert {'term': {'tags': 'bar'}} in filter_

    def test_search_by_tag_ignored(self):
        # firefox57 is in the ignore list, we shouldn't filter the query with
        # it.
        qs = self._filter(data={'tag': 'firefox57'})
        assert 'bool' not in qs['query']

        qs = self._filter(data={'tag': 'foo,firefox57'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'tags': 'foo'}} in filter_
        assert {'term': {'tags': 'firefox57'}} not in filter_

    def test_search_by_author(self):
        qs = self._filter(data={'author': 'fooBar'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        should = filter_[0]['bool']['should']
        assert {'terms': {'listed_authors.id': []}} in should
        assert {'terms': {'listed_authors.username': ['fooBar']}} in should

        qs = self._filter(data={'author': 'foo,bar'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        should = filter_[0]['bool']['should']
        assert {'terms': {'listed_authors.id': []}} in should
        assert {'terms': {'listed_authors.username': ['foo', 'bar']}} in should

        qs = self._filter(data={'author': '123,456'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        should = filter_[0]['bool']['should']
        assert {'terms': {'listed_authors.id': ['123', '456']}} in should
        assert {'terms': {'listed_authors.username': []}} in should

        qs = self._filter(data={'author': '123,bar'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        should = filter_[0]['bool']['should']
        assert {'terms': {'listed_authors.id': ['123']}} in should
        assert {'terms': {'listed_authors.username': ['bar']}} in should

    def test_exclude_addons(self):
        qs = self._filter(data={'exclude_addons': 'fooBar'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']

        # We've got another bool query inside our filter to handle the
        # must_not here.
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        assert 'must' not in filter_[0]['bool']
        must_not = filter_[0]['bool']['must_not']
        assert must_not == [{'terms': {'slug': [u'fooBar']}}]

        qs = self._filter(data={'exclude_addons': 1})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        assert 'must' not in filter_[0]['bool']
        must_not = filter_[0]['bool']['must_not']
        assert must_not == [{'ids': {'values': [u'1']}}]

        qs = self._filter(data={'exclude_addons': 'fooBar,1'})
        assert 'must' not in qs['query']['bool']
        assert 'must_not' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        # elasticsearch-dsl seems to separate our 2 bool clauses instead of
        # keeping them together. It might be a byproduct of using
        # nested+filter. The resulting query is ugly but it should still work,
        # and it's an edge-case anyway, usually clients won't pass 2 different
        # types of identifiers.
        assert len(filter_) == 2
        assert 'must' not in filter_[0]['bool']
        assert 'must' not in filter_[1]['bool']
        must_not = filter_[0]['bool']['must_not']
        assert {'ids': {'values': [u'1']}} in must_not
        must_not = filter_[1]['bool']['must_not']
        assert {'terms': {'slug': [u'fooBar']}} in must_not

    def test_search_by_featured_no_app_no_locale(self):
        qs = self._filter(data={'featured': 'true'})
        assert 'must' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'is_recommended': True}} in filter_

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'featured': 'false'})
        assert context.exception.detail == ['Invalid "featured" parameter.']

    def test_search_by_recommended(self):
        qs = self._filter(data={'recommended': 'true'})
        assert 'must' not in qs['query']['bool']
        filter_ = qs['query']['bool']['filter']
        assert {'term': {'is_recommended': True}} in filter_

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'recommended': 'false'})
        assert context.exception.detail == ['Invalid "recommended" parameter.']

    def test_search_by_color(self):
        qs = self._filter(data={'color': 'ff0000'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 4
        assert inner == [
            {'range': {'colors.s': {'gt': 6.375}}},
            {'range': {'colors.l': {'gt': 12.75, 'lt': 249.9}}},
            {'bool': {'should': [
                {'range': {'colors.h': {'gte': 229}}},
                {'range': {'colors.h': {'lte': 26}}}]}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]

        qs = self._filter(data={'color': '703839'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 4
        assert inner == [
            {'range': {'colors.s': {'gt': 6.375}}},
            {'range': {'colors.l': {'gt': 12.75, 'lt': 249.9}}},
            {'bool': {'should': [
                {'range': {'colors.h': {'gte': 228}}},
                {'range': {'colors.h': {'lte': 25}}}]}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]

        qs = self._filter(data={'color': '#00ffff'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 4
        assert inner == [
            {'range': {'colors.s': {'gt': 6.375}}},
            {'range': {'colors.l': {'gt': 12.75, 'lt': 249.9}}},
            {'range': {'colors.h': {'gte': 101, 'lte': 153}}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]

    def test_search_by_color_grey(self):
        qs = self._filter(data={'color': '#f6f6f6'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 3
        assert inner == [
            {'range': {'colors.s': {'lte': 6.375}}},
            {'range': {'colors.l': {'gte': 182, 'lte': 255}}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]

        qs = self._filter(data={'color': '333'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 3
        assert inner == [
            {'range': {'colors.s': {'lte': 6.375}}},
            {'range': {'colors.l': {'gte': 0, 'lte': 115}}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]

    def test_search_by_color_luminosity_extremes(self):
        qs = self._filter(data={'color': '080603'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 2
        assert inner == [
            {'range': {'colors.l': {'lte': 12.75}}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]

        qs = self._filter(data={'color': 'FEFDFB'})
        filter_ = qs['query']['bool']['filter']
        assert len(filter_) == 1
        inner = filter_[0]['nested']['query']['bool']['filter']
        assert len(inner) == 2
        assert inner == [
            {'range': {'colors.l': {'gte': 249.9}}},
            {'range': {'colors.ratio': {'gte': 0.25}}},
        ]


class TestCombinedFilter(FilterTestsBase):
    """
    Basic test to ensure that when filters are combined they result in the
    expected query structure.

    """
    filter_classes = [SearchQueryFilter, ReviewedContentFilter, SortingFilter]

    def test_combined(self):
        qs = self._filter(data={'q': 'test'})
        bool_ = qs['query']['bool']

        assert 'must_not' not in bool_

        filter_ = bool_['filter']
        assert {'terms': {'status': amo.REVIEWED_STATUSES}} in filter_
        assert {'exists': {'field': 'current_version'}} in filter_
        assert {'term': {'is_disabled': False}} in filter_

        assert qs['sort'] == ['_score']

        should = bool_['must'][0]['function_score']['query']['bool']['should']
        expected = {
            'match': {
                'name_l10n_english': {
                    'analyzer': 'english', 'boost': 5.0, 'query': u'test',
                    'operator': 'and', '_name': 'Match(name_l10n_english)',
                }
            }
        }
        assert expected in should

    def test_filter_featured_sort_random(self):
        qs = self._filter(data={'featured': 'true', 'sort': 'random'})
        bool_ = qs['query']['bool']

        assert 'must_not' not in bool_

        filter_ = bool_['filter']
        assert {'terms': {'status': amo.REVIEWED_STATUSES}} in filter_
        assert {'exists': {'field': 'current_version'}} in filter_
        assert {'term': {'is_disabled': False}} in filter_

        assert qs['sort'] == ['_score']

        assert bool_['must'][0]['function_score']['functions'] == [
            {'random_score': {}}
        ]

    def test_filter_recommended_sort_random(self):
        qs = self._filter(data={'recommended': 'true', 'sort': 'random'})
        bool_ = qs['query']['bool']

        assert 'must_not' not in bool_

        filter_ = bool_['filter']
        assert {'terms': {'status': amo.REVIEWED_STATUSES}} in filter_
        assert {'exists': {'field': 'current_version'}} in filter_
        assert {'term': {'is_disabled': False}} in filter_

        assert qs['sort'] == ['_score']

        assert bool_['must'][0]['function_score']['functions'] == [
            {'random_score': {}}
        ]
