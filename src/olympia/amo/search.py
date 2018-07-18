import os

from django.conf import settings as dj_settings

from django_statsd.clients import statsd
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Q, Search

import olympia.core.logger


log = olympia.core.logger.getLogger('z.es')


DEFAULT_HOSTS = ['localhost:9200']
DEFAULT_TIMEOUT = 5


def get_es(hosts=None, timeout=None, **settings):
    """Create an ES object and return it."""
    # Cheap way of de-None-ifying things
    hosts = hosts or getattr(dj_settings, 'ES_HOSTS', DEFAULT_HOSTS)
    timeout = (
        timeout
        if timeout is not None
        else getattr(dj_settings, 'ES_TIMEOUT', DEFAULT_TIMEOUT)
    )

    if os.environ.get('RUNNING_IN_CI'):
        settings['http_auth'] = ('elastic', 'changeme')

    return Elasticsearch(hosts, timeout=timeout, **settings)


class ES(object):
    def __init__(self, type_, index):
        self.type = type_
        self.index = index
        self.steps = []
        self.start = 0
        self.stop = None
        self.as_list = self.as_dict = False
        self._results_cache = None

    def _clone(self, next_step=None):
        new = self.__class__(self.type, self.index)
        new.steps = list(self.steps)
        if next_step:
            new.steps.append(next_step)
        new.start = self.start
        new.stop = self.stop
        return new

    def values(self, *fields):
        return self._clone(next_step=('values', fields))

    def values_dict(self, *fields):
        return self._clone(next_step=('values_dict', fields))

    def order_by(self, *fields):
        return self._clone(next_step=('order_by', fields))

    def query(self, **kw):
        return self._clone(next_step=('query', kw.items()))

    def filter(self, **kw):
        return self._clone(next_step=('filter', kw.items()))

    def aggregate(self, **kw):
        return self._clone(next_step=('aggregate', kw.items()))

    def source(self, *fields):
        return self._clone(next_step=('source', fields))

    def filter_query_string(self, query_string):
        return self._clone(next_step=('filter_query_string', query_string))

    def extra(self, **kw):
        new = self._clone()
        actions = 'values values_dict order_by query filter aggregate'.split()
        for key, vals in kw.items():
            assert key in actions
            if hasattr(vals, 'items'):
                new.steps.append((key, vals.items()))
            else:
                new.steps.append((key, vals))
        return new

    def count(self):
        if self._results_cache is not None:
            return self._results_cache.count
        else:
            return self[:0].raw()['hits']['total']

    def __len__(self):
        return len(self._do_search())

    def __getitem__(self, k):
        new = self._clone()
        # TODO: validate numbers and ranges
        if isinstance(k, slice):
            new.start, new.stop = k.start or 0, k.stop
            return new
        else:
            new.start, new.stop = k, k + 1
            return list(new)[0]

    def _build_query(self):
        query = Q()

        source = ['id']
        sort = []

        aggregations = {}
        query_string = None
        as_list = as_dict = False

        for action, value in self.steps:
            if action == 'order_by':
                for key in value:
                    if key.startswith('-'):
                        sort.append({key[1:]: 'desc'})
                    else:
                        sort.append(key)
            elif action == 'values':
                source.extend(value)
                as_list, as_dict = True, False
            elif action == 'values_dict':
                if value:
                    source.extend(value)
                as_list, as_dict = False, True
            elif action == 'query':
                query &= self._process_queries(value)
            elif action == 'filter':
                query &= self._process_filters(value)
            elif action == 'source':
                source.extend(value)
            elif action == 'aggregate':
                aggregations.update(value)
            elif action == 'filter_query_string':
                query_string = value
            else:
                raise NotImplementedError(action)

        # If we have a raw query string we are going to apply all sorts
        # of boosts and filters to improve relevance scoring.
        #
        # We are using the same rules that `search.filters:SearchQueryFilter`
        # implements to have a single-source of truth for how our
        # scoring works.
        from olympia.search.filters import SearchQueryFilter

        search = Search().query(query)

        if query_string:
            search = SearchQueryFilter().apply_search_query(
                query_string, search
            )

        if sort:
            search = search.sort(*sort)

        if source:
            search = search.source(source)

        body = search.to_dict()

        # These are manually added for now to simplify a partial port to
        # elasticsearch-dsl
        if self.start:
            body['from'] = self.start
        if self.stop is not None:
            body['size'] = self.stop - self.start
        if aggregations:
            body['aggs'] = aggregations

        self.source, self.as_list, self.as_dict = source, as_list, as_dict
        return body

    def _split(self, string):
        if '__' in string:
            return string.rsplit('__', 1)
        else:
            return string, None

    def _process_filters(self, value):
        value = dict(value)
        filters = []

        for key, val in value.items():
            key, field_action = self._split(key)
            if field_action is None:
                filters.append(Q('term', **{key: val}))
            elif field_action == 'exists':
                if val is not True:
                    raise NotImplementedError(
                        '<field>__exists only works with a "True" value.'
                    )
                filters.append(Q('exists', **{'field': key}))
            elif field_action == 'in':
                filters.append(Q('terms', **{key: val}))
            elif field_action in ('gt', 'gte', 'lt', 'lte'):
                filters.append(Q('range', **{key: {field_action: val}}))
            elif field_action == 'range':
                from_, to = val
                filters.append(Q('range', **{key: {'gte': from_, 'lte': to}}))

        return Q('bool', filter=filters)

    def _process_queries(self, value):
        value = dict(value)
        query = Q()

        for key, val in value.items():
            key, field_action = self._split(key)
            if field_action is None:
                query &= Q('term', **{key: val})
            elif field_action in ('text', 'match'):
                query &= Q('match', **{key: val})
            elif field_action in ('prefix', 'startswith'):
                query &= Q('prefix', **{key: val})
            elif field_action in ('gt', 'gte', 'lt', 'lte'):
                query &= Q('range', **{key: {field_action: val}})
            elif field_action == 'fuzzy':
                query &= Q('fuzzy', **{key: val})

        return query

    def _do_search(self):
        if self._results_cache is None:
            hits = self.raw()
            if self.as_dict:
                ResultClass = DictSearchResults
            elif self.as_list:
                ResultClass = ListSearchResults
            else:
                ResultClass = ObjectSearchResults
            self._results_cache = ResultClass(self.type, hits, self.source)
        return self._results_cache

    def raw(self):
        build_body = self._build_query()

        es = get_es()
        try:
            with statsd.timer('search.es.timer') as timer:
                hits = es.search(
                    body=build_body,
                    index=self.index,
                    doc_type=self.type._meta.db_table,
                )
        except Exception:
            log.error(build_body)
            raise

        statsd.timing('search.es.took', hits['took'])
        log.debug('[%s] [%s] %s' % (hits['took'], timer.ms, build_body))
        return hits

    def __iter__(self):
        return iter(self._do_search())

    def raw_aggregations(self):
        return self._do_search().results.get('aggregations', {})

    @property
    def aggregations(self):
        aggregations = {}
        raw_aggregations = self.raw_aggregations()
        for key, val in raw_aggregations.items():
            aggregations[key] = [v for v in val['buckets']]
        return aggregations


class SearchResults(object):
    def __init__(self, type, results, source):
        self.type = type
        self.took = results['took']
        self.count = results['hits']['total']
        self.results = results
        self.source = source
        self.set_objects(results['hits']['hits'])

    def set_objects(self, hits):
        raise NotImplementedError()

    def __iter__(self):
        return iter(self.objects)

    def __len__(self):
        return len(self.objects)


class DictSearchResults(SearchResults):
    def set_objects(self, hits):
        self.objects = [r['_source'] for r in hits]

        return self.objects


class ListSearchResults(SearchResults):
    def set_objects(self, hits):
        # When fields are specified in `values(...)` we return the fields.
        objs = []
        for hit in hits:
            objs.append(tuple(v for v in hit['_source'].values()))

        self.objects = objs


class ObjectSearchResults(SearchResults):
    def set_objects(self, hits):
        self.ids = [int(r['_id']) for r in hits]
        self.objects = self.type.objects.filter(id__in=self.ids)

    def __iter__(self):
        objs = dict((obj.id, obj) for obj in self.objects)
        return (objs[id] for id in self.ids if id in objs)
