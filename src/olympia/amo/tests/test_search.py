from django.core import paginator

import mock
from nose.tools import eq_, ok_

from olympia import amo, search
from olympia.amo.tests import TestCase, ESTestCaseWithAddons
from olympia.addons.models import Addon


class TestESIndexing(ESTestCaseWithAddons):

    # This needs to be in its own class for data isolation.
    def test_indexed_count(self):
        # Did all the right addons get indexed?
        count = Addon.search().filter(type=1, is_disabled=False).count()
        eq_(count, 4)  # Created in the setUpClass.
        eq_(count,
            Addon.objects.filter(disabled_by_user=False,
                                 status__in=amo.VALID_STATUSES).count())

    def test_get_es_not_mocked(self):
        es = search.get_es()
        assert not issubclass(es.__class__, mock.Mock)


class TestNoESIndexing(TestCase):
    mock_es = True

    def test_no_es(self):
        assert not getattr(self, 'es', False), (
            'TestCase should not have "es" attribute')

    def test_not_indexed(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_PUBLIC)
        assert issubclass(
            Addon.search().filter(id__in=addon.id).count().__class__,
            mock.Mock)

    def test_get_es_mocked(self):
        es = search.get_es()
        assert issubclass(es.__class__, mock.Mock)


class TestES(ESTestCaseWithAddons):

    def test_clone(self):
        # Doing a filter creates a new ES object.
        qs = Addon.search()
        qs2 = qs.filter(type=1)
        assert 'filtered' not in qs._build_query()['query']
        assert 'filtered' in qs2._build_query()['query']

    def test_filter(self):
        qs = Addon.search().filter(type=1)
        eq_(qs._build_query()['query']['filtered']['filter'],
            [{'term': {'type': 1}}])

    def test_in_filter(self):
        qs = Addon.search().filter(type__in=[1, 2])
        eq_(qs._build_query()['query']['filtered']['filter'],
            [{'in': {'type': [1, 2]}}])

    def test_and(self):
        qs = Addon.search().filter(type=1, category__in=[1, 2])
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [{'term': {'type': 1}}, {'in': {'category': [1, 2]}}]}
        eq_(filters.keys(), ['and'])
        ok_({'term': {'type': 1}} in filters['and'])
        ok_({'in': {'category': [1, 2]}} in filters['and'])

    def test_query(self):
        qs = Addon.search().query(type=1)
        eq_(qs._build_query()['query']['function_score']['query'],
            {'term': {'type': 1}})

    def test_query_match(self):
        qs = Addon.search().query(name__match='woo woo')
        eq_(qs._build_query()['query']['function_score']['query'],
            {'match': {'name': 'woo woo'}})

    def test_query_multiple_and_range(self):
        qs = Addon.search().query(type=1, status__gte=1)
        query = qs._build_query()['query']['function_score']['query']
        # Query:
        # {'bool': {'must': [{'term': {'type': 1}},
        #                    {'range': {'status': {'gte': 1}}}, ]}}
        eq_(query.keys(), ['bool'])
        eq_(query['bool'].keys(), ['must'])
        ok_({'term': {'type': 1}} in query['bool']['must'])
        ok_({'range': {'status': {'gte': 1}}} in query['bool']['must'])

    def test_query_or(self):
        qs = Addon.search().query(or_=dict(type=1, status__gte=2))
        query = qs._build_query()['query']['function_score']['query']
        # Query:
        # {'bool': {'should': [{'term': {'type': 1}},
        #                      {'range': {'status': {'gte': 2}}}, ]}}
        eq_(query.keys(), ['bool'])
        eq_(query['bool'].keys(), ['should'])
        ok_({'term': {'type': 1}} in query['bool']['should'])
        ok_({'range': {'status': {'gte': 2}}} in query['bool']['should'])

    def test_query_or_and(self):
        qs = Addon.search().query(or_=dict(type=1, status__gte=2), category=2)
        query = qs._build_query()['query']['function_score']['query']
        # Query:
        # {'bool': {'must': [{'term': {'category': 2}},
        #                    {'bool': {'should': [
        #                        {'term': {'type': 1}},
        #                        {'range': {'status': {'gte': 2}}}, ]}}]}})
        eq_(query.keys(), ['bool'])
        eq_(query['bool'].keys(), ['must'])
        ok_({'term': {'category': 2}} in query['bool']['must'])
        sub_clause = sorted(query['bool']['must'])[0]
        eq_(sub_clause.keys(), ['bool'])
        eq_(sub_clause['bool'].keys(), ['should'])
        ok_({'range': {'status': {'gte': 2}}} in sub_clause['bool']['should'])
        ok_({'term': {'type': 1}} in sub_clause['bool']['should'])

    def test_query_fuzzy(self):
        fuzz = {'boost': 2, 'value': 'woo'}
        qs = Addon.search().query(or_=dict(type=1, status__fuzzy=fuzz))
        query = qs._build_query()['query']['function_score']['query']
        # Query:
        # {'bool': {'should': [{'fuzzy': {'status': fuzz}},
        #                      {'term': {'type': 1}}, ]}})
        eq_(query.keys(), ['bool'])
        eq_(query['bool'].keys(), ['should'])
        ok_({'term': {'type': 1}} in query['bool']['should'])
        ok_({'fuzzy': {'status': fuzz}} in query['bool']['should'])

    def test_order_by_desc(self):
        qs = Addon.search().order_by('-rating')
        eq_(qs._build_query()['sort'], [{'rating': 'desc'}])

    def test_order_by_asc(self):
        qs = Addon.search().order_by('rating')
        eq_(qs._build_query()['sort'], ['rating'])

    def test_order_by_multiple(self):
        qs = Addon.search().order_by('-rating', 'id')
        eq_(qs._build_query()['sort'], [{'rating': 'desc'}, 'id'])

    def test_slice(self):
        qs = Addon.search()[5:12]
        eq_(qs._build_query()['from'], 5)
        eq_(qs._build_query()['size'], 7)

    def test_filter_or(self):
        qs = Addon.search().filter(type=1).filter(or_=dict(status=1, app=2))
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [
        #     {'term': {'type': 1}},
        #     {'or': [{'term': {'status': 1}}, {'term': {'app': 2}}]},
        # ]}
        eq_(filters.keys(), ['and'])
        ok_({'term': {'type': 1}} in filters['and'])
        or_clause = sorted(filters['and'])[0]
        eq_(or_clause.keys(), ['or'])
        ok_({'term': {'status': 1}} in or_clause['or'])
        ok_({'term': {'app': 2}} in or_clause['or'])

        qs = Addon.search().filter(type=1, or_=dict(status=1, app=2))
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [
        #     {'term': {'type': 1}},
        #     {'or': [{'term': {'status': 1}}, {'term': {'app': 2}}]},
        # ]}
        eq_(filters.keys(), ['and'])
        ok_({'term': {'type': 1}} in filters['and'])
        or_clause = sorted(filters['and'])[0]
        eq_(or_clause.keys(), ['or'])
        ok_({'term': {'status': 1}} in or_clause['or'])
        ok_({'term': {'app': 2}} in or_clause['or'])

    def test_slice_stop(self):
        qs = Addon.search()[:6]
        eq_(qs._build_query()['size'], 6)

    def test_slice_stop_zero(self):
        qs = Addon.search()[:0]
        eq_(qs._build_query()['size'], 0)

    def test_getitem(self):
        addons = list(Addon.search())
        eq_(addons[0], Addon.search()[0])

    def test_iter(self):
        qs = Addon.search().filter(type=1, is_disabled=False)
        eq_(len(qs), len(list(qs)))

    def test_count(self):
        eq_(Addon.search().count(), 6)

    def test_count_uses_cached_results(self):
        qs = Addon.search()
        qs._results_cache = mock.Mock()
        qs._results_cache.count = mock.sentinel.count
        eq_(qs.count(), mock.sentinel.count)

    def test_len(self):
        qs = Addon.search()
        qs._results_cache = [1]
        eq_(len(qs), 1)

    def test_gte(self):
        qs = Addon.search().filter(type__in=[1, 2], status__gte=4)
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [
        #     {'in': {'type': [1, 2]}},
        #     {'range': {'status': {'gte': 4}}},
        # ]}
        eq_(filters.keys(), ['and'])
        ok_({'in': {'type': [1, 2]}} in filters['and'])
        ok_({'range': {'status': {'gte': 4}}} in filters['and'])

    def test_lte(self):
        qs = Addon.search().filter(type__in=[1, 2], status__lte=4)
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [
        #     {'in': {'type': [1, 2]}},
        #     {'range': {'status': {'lte': 4}}},
        # ]}
        eq_(filters.keys(), ['and'])
        ok_({'in': {'type': [1, 2]}} in filters['and'])
        ok_({'range': {'status': {'lte': 4}}} in filters['and'])

    def test_gt(self):
        qs = Addon.search().filter(type__in=[1, 2], status__gt=4)
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [
        #     {'in': {'type': [1, 2]}},
        #     {'range': {'status': {'gt': 4}}},
        # ]}
        eq_(filters.keys(), ['and'])
        ok_({'in': {'type': [1, 2]}} in filters['and'])
        ok_({'range': {'status': {'gt': 4}}} in filters['and'])

    def test_lt(self):
        qs = Addon.search().filter(type__in=[1, 2], status__lt=4)
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [
        #     {'range': {'status': {'lt': 4}}},
        #     {'in': {'type': [1, 2]}},
        # ]}
        eq_(filters.keys(), ['and'])
        ok_({'range': {'status': {'lt': 4}}} in filters['and'])
        ok_({'in': {'type': [1, 2]}} in filters['and'])

    def test_lt2(self):
        qs = Addon.search().filter(status__lt=4)
        eq_(qs._build_query()['query']['filtered']['filter'],
            [{'range': {'status': {'lt': 4}}}])

    def test_range(self):
        qs = Addon.search().filter(date__range=('a', 'b'))
        eq_(qs._build_query()['query']['filtered']['filter'],
            [{'range': {'date': {'gte': 'a', 'lte': 'b'}}}])

    def test_prefix(self):
        qs = Addon.search().query(name__startswith='woo')
        eq_(qs._build_query()['query']['function_score']['query'],
            {'prefix': {'name': 'woo'}})

    def test_values(self):
        qs = Addon.search().values('name')
        eq_(qs._build_query()['fields'], ['id', 'name'])

    def test_values_result(self):
        addons = [{'id': [a.id], 'slug': [a.slug]} for a in self._addons]
        qs = Addon.search().values_dict('slug').order_by('id')
        eq_(list(qs), addons)

    def test_values_dict(self):
        qs = Addon.search().values_dict('name')
        eq_(qs._build_query()['fields'], ['id', 'name'])

    def test_empty_values_dict(self):
        qs = Addon.search().values_dict()
        assert 'fields' not in qs._build_query()

    def test_values_dict_result(self):
        addons = [{'id': [a.id], 'slug': [a.slug]} for a in self._addons]
        qs = Addon.search().values_dict('slug').order_by('id')
        eq_(list(qs), list(addons))

    def test_empty_values_dict_result(self):
        qs = Addon.search().values_dict()
        # Look for some of the keys we expect.
        for key in ('id', 'name', 'status', 'app'):
            assert key in qs[0].keys(), qs[0].keys()

    def test_object_result(self):
        qs = Addon.search().filter(id=self._addons[0].id)[:1]
        eq_(self._addons[:1], list(qs))

    def test_object_result_slice(self):
        addon = self._addons[0]
        qs = Addon.search().filter(id=addon.id)
        eq_(addon, qs[0])

    def test_extra_bad_key(self):
        with self.assertRaises(AssertionError):
            Addon.search().extra(x=1)

    def test_extra_values(self):
        qs = Addon.search().extra(values=['name'])
        eq_(qs._build_query()['fields'], ['id', 'name'])

        qs = Addon.search().values('status').extra(values=['name'])
        eq_(qs._build_query()['fields'], ['id', 'status', 'name'])

    def test_extra_values_dict(self):
        qs = Addon.search().extra(values_dict=['name'])
        eq_(qs._build_query()['fields'], ['id', 'name'])

        qs = Addon.search().values_dict('status').extra(values_dict=['name'])
        eq_(qs._build_query()['fields'], ['id', 'status', 'name'])

    def test_extra_order_by(self):
        qs = Addon.search().extra(order_by=['-rating'])
        eq_(qs._build_query()['sort'], [{'rating': 'desc'}])

        qs = Addon.search().order_by('-id').extra(order_by=['-rating'])
        eq_(qs._build_query()['sort'], [{'id': 'desc'}, {'rating': 'desc'}])

    def test_extra_query(self):
        qs = Addon.search().extra(query={'type': 1})
        eq_(qs._build_query()['query']['function_score']['query'],
            {'term': {'type': 1}})

        qs = Addon.search().filter(status=1).extra(query={'type': 1})
        filtered = qs._build_query()['query']['filtered']
        eq_(filtered['query']['function_score']['query'],
            {'term': {'type': 1}})
        eq_(filtered['filter'], [{'term': {'status': 1}}])

    def test_extra_filter(self):
        qs = Addon.search().extra(filter={'category__in': [1, 2]})
        eq_(qs._build_query()['query']['filtered']['filter'],
            [{'in': {'category': [1, 2]}}])

        qs = (Addon.search().filter(type=1)
              .extra(filter={'category__in': [1, 2]}))
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [{'term': {'type': 1}}, {'in': {'category': [1, 2]}}, ]}
        eq_(filters.keys(), ['and'])
        ok_({'term': {'type': 1}} in filters['and'])
        ok_({'in': {'category': [1, 2]}} in filters['and'])

    def test_extra_filter_or(self):
        qs = Addon.search().extra(filter={'or_': {'status': 1, 'app': 2}})
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # [{'or': [{'term': {'status': 1}}, {'term': {'app': 2}}]}])
        eq_(len(filters), 1)
        eq_(filters[0].keys(), ['or'])
        ok_({'term': {'status': 1}} in filters[0]['or'])
        ok_({'term': {'app': 2}} in filters[0]['or'])

        qs = (Addon.search().filter(type=1)
              .extra(filter={'or_': {'status': 1, 'app': 2}}))
        filters = qs._build_query()['query']['filtered']['filter']
        # Filters:
        # {'and': [{'term': {'type': 1}},
        #          {'or': [{'term': {'status': 1}}, {'term': {'app': 2}}]}]})
        eq_(filters.keys(), ['and'])
        ok_({'term': {'type': 1}} in filters['and'])
        or_clause = sorted(filters['and'])[0]
        eq_(or_clause.keys(), ['or'])
        ok_({'term': {'status': 1}} in or_clause['or'])
        ok_({'term': {'app': 2}} in or_clause['or'])

    def test_facet_range(self):
        facet = {'range': {'status': [{'lte': 3}, {'gte': 5}]}}
        # Pass a copy so edits aren't propagated back here.
        qs = Addon.search().filter(app=1).facet(by_status=dict(facet))
        eq_(qs._build_query()['query']['filtered']['filter'],
            [{'term': {'app': 1}}])
        eq_(qs._build_query()['facets'], {'by_status': facet})

    def test_source(self):
        qs = Addon.search().source('versions')
        eq_(qs._build_query()['_source'], ['versions'])


class TestPaginator(ESTestCaseWithAddons):

    def setUp(self):
        super(TestPaginator, self).setUp()
        self.request = request = mock.Mock()
        request.GET.get.return_value = 1
        request.GET.urlencode.return_value = ''
        request.path = ''

    def test_es_paginator(self):
        qs = Addon.search()
        pager = amo.utils.paginate(self.request, qs)
        assert isinstance(pager.paginator, amo.utils.ESPaginator)

    def test_validate_number(self):
        p = amo.utils.ESPaginator(Addon.search(), 20)
        # A bad number raises an exception.
        with self.assertRaises(paginator.PageNotAnInteger):
            p.page('a')

        # A large number is ignored.
        p.page(99)

    def test_count(self):
        p = amo.utils.ESPaginator(Addon.search(), 20)
        eq_(p._count, None)
        p.page(1)
        eq_(p.count, Addon.search().count())
