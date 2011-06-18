import logging
from operator import itemgetter

from django.conf import settings

import elasticutils
from statsd import statsd

log = logging.getLogger('z.es')


class ES(object):

    def __init__(self, type_):
        self.type = type_
        self.steps = []
        self.start = 0
        self.stop = None
        self.as_list = self.as_dict = False
        self._results_cache = None

    def _clone(self, next_step=None):
        new = self.__class__(self.type)
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

    # This is a lame hack.
    def filter_or(self, **kw):
        return self._clone(next_step=('filter_or', kw.items()))

    def extra(self, **kw):
        new = self._clone()
        actions = 'values values_dict order_by query filter filter_or'.split()
        for key, vals in kw.items():
            assert key in actions
            if hasattr(vals, 'items'):
                new.steps.append((key, vals.items()))
            else:
                new.steps.append((key, vals))
        return new

    def count(self):
        hits = self._get_results()
        return hits['hits']['total']

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
        # start, stop
        filters = []
        queries = []
        sort = []
        fields = ['id']
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
                fields.extend(value)
                as_list, as_dict = False, True
            elif action == 'query':
                queries.extend(self._process_queries(value))
            elif action == 'filter':
                filters.extend(self._process_filters(value))
            elif action == 'filter_or':
                filters.append({'or': self._process_filters(value)})
            else:
                raise NotImplementedError(action)

        qs = {}
        if len(filters) > 1:
            qs['filter'] = {'and': filters}
        elif filters:
            qs['filter'] = filters[0]

        if len(queries) > 1:
            raise NotImplementedError()
        elif queries:
            qs['query'] = queries[0]

        if fields:
            qs['fields'] = fields
        if sort:
            qs['sort'] = sort
        if self.start:
            qs['from'] = self.start
        if self.stop:
            qs['size'] = self.stop - self.start

        self.fields, self.as_list, self.as_dict = fields, as_list, as_dict
        return qs

    def _split(self, string):
        if '__' in string:
            return string.rsplit('__', 1)
        else:
            return string, None

    def _process_filters(self, value):
        rv = []
        for key, val in value:
            key, field_action = self._split(key)
            if field_action is None:
                rv.append({'term': {key: val}})
            if field_action == 'in':
                rv.append({'in': {key: val}})
            elif field_action in ('gt', 'gte', 'lt', 'lte'):
                rv.append({'range': {key: {field_action: val}}})
        return rv

    def _process_queries(self, value):
        rv = []
        for key, val in value:
            key, field_action = self._split(key)
            if field_action is None:
                rv.append({'term': {key: val}})
            elif field_action == 'startswith':
                rv.append({'prefix': {key: val}})
        return rv

    def _do_search(self):
        if not self._results_cache:
            hits = self._get_results()
            if self.as_dict:
                ResultClass = DictSearchResults
            elif self.as_list:
                ResultClass = ListSearchResults
            else:
                ResultClass = ObjectSearchResults
            self._results_cache = ResultClass(self.type, hits, self.fields)
        return self._results_cache

    def _get_results(self):
        qs = self._build_query()
        es = elasticutils.get_es()
        hits = es.search(qs, settings.ES_INDEX, self.type._meta.app_label)
        statsd.timing('search', hits['took'])
        log.debug('[%s] %s' % (hits['took'], qs))
        return hits

    def __iter__(self):
        return iter(self._do_search())


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
        key = 'fields' if self.fields else '_source'
        self.objects = [r[key] for r in hits]


class ListSearchResults(SearchResults):

    def set_objects(self, hits):
        if self.fields:
            getter = itemgetter(*self.fields)
            objs = [getter(r['fields']) for r in hits]
        else:
            objs = [r['_source'].values() for r in hits]
        self.objects = objs


class ObjectSearchResults(SearchResults):

    def set_objects(self, hits):
        self.ids = [int(r['_id']) for r in hits]
        self.objects = self.type.objects.filter(id__in=self.ids)

    def __iter__(self):
        objs = dict((obj.id, obj) for obj in self.objects)
        return (objs[id] for id in self.ids if id in objs)
