import os

from django.conf import settings as dj_settings

from django_statsd.clients import statsd
from elasticsearch import Elasticsearch

import olympia.core.logger


log = olympia.core.logger.getLogger('z.es')


DEFAULT_HOSTS = ['localhost:9200']
DEFAULT_TIMEOUT = 5


def get_es(hosts=None, timeout=None, **settings):
    """Create an ES object and return it."""
    # Cheap way of de-None-ifying things
    hosts = hosts or getattr(dj_settings, 'ES_HOSTS', DEFAULT_HOSTS)
    timeout = (timeout if timeout is not None else
               getattr(dj_settings, 'ES_TIMEOUT', DEFAULT_TIMEOUT))

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

    def score(self, function):
        return self._clone(next_step=('score', function))

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
        if self._results_cache:
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
        filters = []
        queries = []
        sort = []
        source = ['id']
        aggregations = {}
        functions = [
            # By default, boost results using the field in the index named...
            # boost.
            {'field_value_factor': {'field': 'boost', 'missing': 1.0}}
        ]
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
                queries.extend(self._process_queries(value))
            elif action == 'filter':
                filters.extend(self._process_filters(value))
            elif action == 'source':
                source.extend(value)
            elif action == 'aggregate':
                aggregations.update(value)
            elif action == 'score':
                functions.append(value)
            else:
                raise NotImplementedError(action)

        if len(queries) > 1:
            qs = {'bool': {'must': queries}}
        elif queries:
            qs = queries[0]
        else:
            qs = {"match_all": {}}

        if functions:
            qs = {
                "function_score": {
                    "query": qs,
                    "functions": functions
                }
            }

        if filters:
            if len(filters) > 1:
                filters = {'bool': {'must': filters}}

            qs = {
                "bool": {
                    "must": qs,
                    "filter": filters
                }
            }

        body = {"query": qs}
        if sort:
            body['sort'] = sort
        if self.start:
            body['from'] = self.start
        if self.stop is not None:
            body['size'] = self.stop - self.start
        if aggregations:
            body['aggs'] = aggregations

        if source:
            body['_source'] = source

        self.source, self.as_list, self.as_dict = source, as_list, as_dict
        return body

    def _split(self, string):
        if '__' in string:
            return string.rsplit('__', 1)
        else:
            return string, None

    def _process_filters(self, value):
        rv = []
        value = dict(value)
        or_ = value.pop('or_', [])
        for key, val in value.items():
            key, field_action = self._split(key)
            if field_action is None:
                rv.append({'term': {key: val}})
            elif field_action == 'exists':
                if val is not True:
                    raise NotImplementedError(
                        '<field>__exists only works with a "True" value.')
                rv.append({'exists': {'field': key}})
            elif field_action == 'in':
                rv.append({'terms': {key: val}})
            elif field_action in ('gt', 'gte', 'lt', 'lte'):
                rv.append({'range': {key: {field_action: val}}})
            elif field_action == 'range':
                from_, to = val
                rv.append({'range': {key: {'gte': from_, 'lte': to}}})
        if or_:
            rv.append({'should': self._process_filters(or_.items())})
        return rv

    def _process_queries(self, value):
        rv = []
        value = dict(value)
        or_ = value.pop('or_', {})
        extend = value.pop('extend_', [])

        for key, val in value.items():
            key, field_action = self._split(key)
            if field_action is None:
                rv.append({'term': {key: val}})
            elif field_action in ('text', 'match'):
                rv.append({'match': {key: val}})
            elif field_action in ('prefix', 'startswith'):
                rv.append({'prefix': {key: val}})
            elif field_action in ('gt', 'gte', 'lt', 'lte'):
                rv.append({'range': {key: {field_action: val}}})
            elif field_action == 'fuzzy':
                rv.append({'fuzzy': {key: val}})
        if or_:
            rv.append({'bool': {'should': self._process_queries(or_.items())}})
        if extend:
            rv.extend(extend)

        return rv

    def _do_search(self):
        if not self._results_cache:
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
                    doc_type=self.type._meta.db_table
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
