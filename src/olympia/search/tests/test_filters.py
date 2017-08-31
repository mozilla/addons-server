# -*- coding: utf-8 -*-
from django.test.client import RequestFactory

from elasticsearch_dsl import Search
from mock import Mock
from rest_framework import serializers

from olympia import amo
from olympia.amo.tests import create_switch, TestCase
from olympia.constants.categories import CATEGORIES
from olympia.search.filters import (
    InternalSearchParameterFilter, ReviewedContentFilter,
    SearchParameterFilter, SearchQueryFilter, SortingFilter)


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

    def _test_q(self):
        qs = self._filter(data={'q': 'tea pot'})
        # Spot check a few queries.
        should = qs['query']['function_score']['query']['bool']['should']

        expected = {
            'match_phrase': {
                'name': {
                    'query': 'tea pot', 'boost': 4, 'slop': 1
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
                'name_l10n_english': {
                    'query': 'tea pot', 'boost': 2.5,
                    'analyzer': 'english'
                }
            }
        }
        assert expected in should

        expected = {
            'match_phrase': {
                'description_l10n_english': {
                    'query': 'tea pot',
                    'boost': 0.6,
                    'analyzer': 'english'
                }
            }
        }
        assert expected in should

        functions = qs['query']['function_score']['functions']
        assert functions[0] == {'field_value_factor': {'field': 'boost'}}
        return qs

    def test_q(self):
        qs = self._test_q()
        functions = qs['query']['function_score']['functions']
        assert len(functions) == 1

    def test_fuzzy_single_word(self):
        qs = self._filter(data={'q': 'blah'})
        should = qs['query']['function_score']['query']['bool']['should']
        expected = {
            'fuzzy': {
                'name': {
                    'boost': 2, 'prefix_length': 4, 'value': 'blah'
                }
            }
        }
        assert expected in should

    def test_fuzzy_multi_word(self):
        qs = self._filter(data={'q': 'search terms'})
        should = qs['query']['function_score']['query']['bool']['should']
        expected = {
            'fuzzy': {
                'name': {
                    'boost': 2, 'prefix_length': 4, 'value': 'search terms'
                }
            }
        }
        assert expected in should

    def test_webextension_boost(self):
        create_switch('boost-webextensions-in-search')

        # Repeat base test with the switch enabled.
        qs = self._test_q()
        functions = qs['query']['function_score']['functions']

        assert len(functions) == 2
        assert functions[1] == {
            'weight': 2.0,  # WEBEXTENSIONS_WEIGHT,
            'filter': {'term': {'current_version.files.is_webextension': True}}
        }


class TestReviewedContentFilter(FilterTestsBase):

    filter_classes = [ReviewedContentFilter]

    def test_status(self):
        qs = self._filter(self.req)
        must = qs['query']['bool']['must']
        must_not = qs['query']['bool']['must_not']

        assert {'terms': {'status': amo.REVIEWED_STATUSES}} in must
        assert {'exists': {'field': 'current_version'}} in must
        assert {'term': {'is_disabled': True}} in must_not
        assert {'term': {'is_deleted': True}} in must_not


class TestSortingFilter(FilterTestsBase):

    filter_classes = [SortingFilter]

    def _reformat_order(self, key):
        # elasticsearch-dsl transforms '-something' for us, so we have to
        # expect the sort param in this format when we inspect the resulting
        # queryset object.
        return {key[1:]: {'order': 'desc'}} if key.startswith('-') else key

    def test_sort_default(self):
        qs = self._filter(data={'q': 'something'})
        assert qs['sort'] == [self._reformat_order('-_score')]

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

        # If the sort query is wrong.
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'sort': ['LOLWRONG,created']})
        assert context.exception.detail == ['Invalid "sort" parameter.']


class TestSearchParameterFilter(FilterTestsBase):
    filter_classes = [SearchParameterFilter]

    def test_search_by_type_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'type': unicode(amo.ADDON_EXTENSION + 666)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'type': 'nosuchtype'})
        assert context.exception.detail == ['Invalid "type" parameter.']

    def test_search_by_type_id(self):
        qs = self._filter(data={'type': unicode(amo.ADDON_EXTENSION)})
        must = qs['query']['bool']['must']
        assert {'term': {'type': amo.ADDON_EXTENSION}} in must

        qs = self._filter(data={'type': unicode(amo.ADDON_PERSONA)})
        must = qs['query']['bool']['must']
        assert {'term': {'type': amo.ADDON_PERSONA}} in must

    def test_search_by_type_string(self):
        qs = self._filter(data={'type': 'extension'})
        must = qs['query']['bool']['must']
        assert {'term': {'type': amo.ADDON_EXTENSION}} in must

        qs = self._filter(data={'type': 'persona'})
        must = qs['query']['bool']['must']
        assert {'term': {'type': amo.ADDON_PERSONA}} in must

    def test_search_by_app_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'app': unicode(amo.FIREFOX.id + 666)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'app': 'nosuchapp'})
        assert context.exception.detail == ['Invalid "app" parameter.']

    def test_search_by_app_id(self):
        qs = self._filter(data={'app': unicode(amo.FIREFOX.id)})
        must = qs['query']['bool']['must']
        assert {'term': {'app': amo.FIREFOX.id}} in must

        qs = self._filter(data={'app': unicode(amo.THUNDERBIRD.id)})
        must = qs['query']['bool']['must']
        assert {'term': {'app': amo.THUNDERBIRD.id}} in must

    def test_search_by_app_string(self):
        qs = self._filter(data={'app': 'firefox'})
        must = qs['query']['bool']['must']
        assert {'term': {'app': amo.FIREFOX.id}} in must

        qs = self._filter(data={'app': 'thunderbird'})
        must = qs['query']['bool']['must']
        assert {'term': {'app': amo.THUNDERBIRD.id}} in must

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
        must = qs['query']['bool']['must']
        assert {'term': {'app': amo.FIREFOX.id}} in must
        assert {'range': {'current_version.compatible_apps.1.min':
                {'lte': 46000000200100}}} in must
        assert {'range': {'current_version.compatible_apps.1.max':
                {'gte': 46000000000100}}} in must

    def test_search_by_platform_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'platform': unicode(amo.PLATFORM_WIN.id + 42)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'platform': 'nosuchplatform'})
        assert context.exception.detail == ['Invalid "platform" parameter.']

    def test_search_by_platform_id(self):
        qs = self._filter(data={'platform': unicode(amo.PLATFORM_WIN.id)})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_WIN.id, amo.PLATFORM_ALL.id]}} in must

        qs = self._filter(data={'platform': unicode(amo.PLATFORM_LINUX.id)})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_LINUX.id, amo.PLATFORM_ALL.id]}} in must

    def test_search_by_platform_string(self):
        qs = self._filter(data={'platform': 'windows'})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_WIN.id, amo.PLATFORM_ALL.id]}} in must

        qs = self._filter(data={'platform': 'win'})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_WIN.id, amo.PLATFORM_ALL.id]}} in must

        qs = self._filter(data={'platform': 'darwin'})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_MAC.id, amo.PLATFORM_ALL.id]}} in must

        qs = self._filter(data={'platform': 'mac'})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_MAC.id, amo.PLATFORM_ALL.id]}} in must

        qs = self._filter(data={'platform': 'macosx'})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_MAC.id, amo.PLATFORM_ALL.id]}} in must

        qs = self._filter(data={'platform': 'linux'})
        must = qs['query']['bool']['must']
        assert {'terms': {'platforms': [
            amo.PLATFORM_LINUX.id, amo.PLATFORM_ALL.id]}} in must

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
        must = qs['query']['bool']['must']
        assert {'term': {'category': category.id}} in must

    def test_search_by_category_id(self):
        qs = self._filter(data={
            'category': 1,
            'app': 'firefox',
            'type': 'extension'
        })
        must = qs['query']['bool']['must']
        assert {'term': {'category': 1}} in must

    def test_search_by_category_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(
                data={'category': 666, 'app': 'firefox', 'type': 'extension'})
        assert context.exception.detail == ['Invalid "category" parameter.']

    def test_search_by_tag(self):
        qs = self._filter(data={'tag': 'foo'})
        must = qs['query']['bool']['must']
        assert {'term': {'tags': 'foo'}} in must

        qs = self._filter(data={'tag': 'foo,bar'})
        must = qs['query']['bool']['must']
        assert {'term': {'tags': 'foo'}} in must
        assert {'term': {'tags': 'bar'}} in must

    def test_search_by_author(self):
        qs = self._filter(data={'author': 'fooBar'})
        must = qs['query']['bool']['must']
        assert {'terms': {'listed_authors.username': ['fooBar']}} in must

        qs = self._filter(data={'author': 'foo,bar'})
        must = qs['query']['bool']['must']
        assert {'terms': {'listed_authors.username': ['foo', 'bar']}} in must


class TestInternalSearchParameterFilter(TestSearchParameterFilter):
    filter_classes = [InternalSearchParameterFilter]

    def test_search_by_status_invalid(self):
        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'status': unicode(amo.STATUS_PUBLIC + 999)})

        with self.assertRaises(serializers.ValidationError) as context:
            self._filter(data={'status': 'nosuchstatus'})
        assert context.exception.detail == ['Invalid "status" parameter.']

    def test_search_by_status_id(self):
        qs = self._filter(data={'status': unicode(amo.STATUS_PUBLIC)})
        must = qs['query']['bool']['must']
        assert {'term': {'status': amo.STATUS_PUBLIC}} in must

        qs = self._filter(data={'status': unicode(amo.STATUS_NULL)})
        must = qs['query']['bool']['must']
        assert {'term': {'status': amo.STATUS_NULL}} in must

    def test_search_by_status_string(self):
        qs = self._filter(data={'status': 'public'})
        must = qs['query']['bool']['must']
        assert {'term': {'status': amo.STATUS_PUBLIC}} in must

        qs = self._filter(data={'status': 'incomplete'})
        must = qs['query']['bool']['must']
        assert {'term': {'status': amo.STATUS_NULL}} in must


class TestCombinedFilter(FilterTestsBase):
    """
    Basic test to ensure that when filters are combined they result in the
    expected query structure.

    """
    filter_classes = [SearchQueryFilter, ReviewedContentFilter, SortingFilter]

    def test_combined(self):
        qs = self._filter(data={'q': 'test'})
        filtered = qs['query']['bool']
        assert filtered['must'][2]['function_score']

        must = filtered['must']
        assert {'terms': {'status': amo.REVIEWED_STATUSES}} in must

        must_not = filtered['must_not']
        assert {'term': {'is_disabled': True}} in must_not

        assert qs['sort'] == [{'_score': {'order': 'desc'}}]

        should = must[2]['function_score']['query']['bool']['should']
        expected = {
            'match': {
                'name_l10n_english': {
                    'analyzer': 'english', 'boost': 2.5, 'query': u'test'
                }
            }
        }
        assert expected in should
