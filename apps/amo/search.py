import logging

from django.conf import settings as dj_settings

from django_statsd.clients import statsd
from elasticsearch import Elasticsearch


log = logging.getLogger('z.es')


DEFAULT_HOSTS = ['localhost:9200']
DEFAULT_TIMEOUT = 5
DEFAULT_INDEXES = ['default']
DEFAULT_DUMP_CURL = None


def get_es(hosts=None, timeout=None, **settings):
    """Create an ES object and return it."""
    # Cheap way of de-None-ifying things
    hosts = hosts or getattr(dj_settings, 'ES_HOSTS', DEFAULT_HOSTS)
    timeout = (timeout if timeout is not None else
               getattr(dj_settings, 'ES_TIMEOUT', DEFAULT_TIMEOUT))

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

    def facet(self, **kw):
        return self._clone(next_step=('facet', kw.items()))

    def source(self, *fields):
        return self._clone(next_step=('source', fields))

    def extra(self, **kw):
        new = self._clone()
        actions = 'values values_dict order_by query filter facet'.split()
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
        fields = ['id']
        source = []
        facets = {}
        as_list = as_dict = False
        for action, value in self.steps:
            if action == 'order_by':
                for key in value:
                    if key.startswith('-'):
                        sort.append({key[1:]: 'desc'})
                    else:
                        sort.append(key)
            elif action == 'values':
                fields.extend(value)
                as_list, as_dict = True, False
            elif action == 'values_dict':
                if not value:
                    fields = []
                else:
                    fields.extend(value)
                as_list, as_dict = False, True
            elif action == 'query':
                queries.extend(self._process_queries(value))
            elif action == 'filter':
                filters.extend(self._process_filters(value))
            elif action == 'source':
                source.extend(value)
            elif action == 'facet':
                facets.update(value)
            else:
                raise NotImplementedError(action)

        if len(queries) > 1:
            qs = {'bool': {'must': queries}}
        elif queries:
            qs = queries[0]
        else:
            qs = {"match_all": {}}

        qs = {
            "function_score": {
                "query": qs,
                "functions": [{"field_value_factor": {"field": "boost"}}]
            }
        }

        if filters:
            if len(filters) > 1:
                filters = {"and": filters}
            qs = {
                "filtered": {
                    "query": qs,
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
        if facets:
            body['facets'] = facets

        if fields:
            body['fields'] = fields
        # As per version 1.0, ES has deprecated loading fields not stored from
        # '_source', plus non leaf fields are not allowed in fields.
        if source:
            body['_source'] = source

        self.fields, self.as_list, self.as_dict = fields, as_list, as_dict
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
            if field_action == 'in':
                rv.append({'in': {key: val}})
            elif field_action in ('gt', 'gte', 'lt', 'lte'):
                rv.append({'range': {key: {field_action: val}}})
            elif field_action == 'range':
                from_, to = val
                rv.append({'range': {key: {'gte': from_, 'lte': to}}})
        if or_:
            rv.append({'or': self._process_filters(or_.items())})
        return rv

    def _process_queries(self, value):
        rv = []
        value = dict(value)
        or_ = value.pop('or_', [])
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
            self._results_cache = ResultClass(self.type, hits, self.fields)
        return self._results_cache

    def raw(self):
        qs = self._build_query()
        es = get_es()
        try:
            with statsd.timer('search.es.timer') as timer:
                hits = es.search(
                    body=qs,
                    index=self.index,
                    doc_type=self.type._meta.db_table
                )
        except Exception:
            log.error(qs)
            raise
        statsd.timing('search.es.took', hits['took'])
        log.debug('[%s] [%s] %s' % (hits['took'], timer.ms, qs))
        return hits

    def __iter__(self):
        return iter(self._do_search())

    def raw_facets(self):
        return self._do_search().results.get('facets', {})

    @property
    def facets(self):
        facets = {}
        for key, val in self.raw_facets().items():
            if val['_type'] == 'terms':
                facets[key] = [v for v in val['terms']]
            elif val['_type'] == 'range':
                facets[key] = [v for v in val['ranges']]
        return facets


class SearchResults(object):

    def __init__(self, type, results, fields):
        self.type = type
        self.took = results['took']
        self.count = results['hits']['total']
        self.results = results
        self.fields = fields
        self.set_objects(results['hits']['hits'])

    def set_objects(self, hits):
        raise NotImplementedError()

    def __iter__(self):
        return iter(self.objects)

    def __len__(self):
        return len(self.objects)


class DictSearchResults(SearchResults):

    def set_objects(self, hits):
        objs = []

        if self.fields:
            # When fields are specified in `values_dict(...)` we return the
            # fields. Each field is coerced to a list to match the
            # Elasticsearch >= 1.0 style.
            for h in hits:
                hit = {}
                fields = h['fields']
                # If source is returned, it means that it has been asked, so
                # take it.
                if '_source' in h:
                    fields.update(h['_source'])
                for field, value in fields.items():
                    if type(value) != list:
                        value = [value]
                    hit[field] = value
                objs.append(hit)
            self.objects = objs
        else:
            self.objects = [r['_source'] for r in hits]

        return self.objects


class ListSearchResults(SearchResults):

    def set_objects(self, hits):
        key = 'fields' if self.fields else '_source'

        # When fields are specified in `values(...)` we return the fields. Each
        # field is coerced to a list to match the Elasticsearch >= 1.0 style.
        objs = []
        for hit in hits:
            objs.append(tuple([v] if key == 'fields' and type(v) != list else v
                              for v in hit[key].values()))

        self.objects = objs


class ObjectSearchResults(SearchResults):

    def set_objects(self, hits):
        self.ids = [int(r['_id']) for r in hits]
        self.objects = self.type.objects.filter(id__in=self.ids)

    def __iter__(self):
        objs = dict((obj.id, obj) for obj in self.objects)
        return (objs[id] for id in self.ids if id in objs)
