import logging

from django.conf import settings

import elasticutils
from statsd import statsd

log = logging.getLogger('z.es')


class ES(object):

    def __init__(self, type_):
        self.type = type_
        self.filters = {}
        self.in_ = {}
        self.queries = {}
        self.fields = ['id']
        self.ordering = []
        self.start = 0
        self.stop = None
        self._results_cache = None

    def _clone(self):
        new = self.__class__(self.type)
        new.filters = dict(self.filters)
        new.in_ = dict(self.in_)
        new.queries = dict(self.queries)
        new.fields = list(self.fields)
        new.ordering = list(self.ordering)
        new.start = self.start
        new.stop = self.stop
        return new

    def values(self, *fields):
        new = self._clone()
        new.fields.extend(fields)
        return new

    def order_by(self, *fields):
        new = self._clone()
        for field in fields:
            if field.startswith('-'):
                new.ordering.append({field[1:]: 'desc'})
            else:
                new.ordering.append(field)
        return new

    def query(self, **kw):
        new = self._clone()
        new.queries.update(kw)
        return new

    def filter(self, **kw):
        new = self._clone()
        for key, value in kw.items():
            if key.endswith('__in'):
                new.in_[key[:-4]] = value
            else:
                new.filters[key] = value
        return new

    def count(self):
        num = self._do_search().count
        self._results_cache = None
        return num

    __len__ = count

    def __getitem__(self, k):
        # TODO: validate numbers and ranges
        if isinstance(k, slice):
            self.start, self.stop = k.start, k.stop
            return self
        else:
            self.start, self.stop = k, k + 1
            return list(self)[0]

    def _build_query(self):
        qs = {}
        if self.queries:
            qs['query'] = {'term': self.queries}

        if len(self.filters) + len(self.in_) > 1:
            qs['filter'] = {'and': []}
            and_ = qs['filter']['and']
            for key, value in self.filters.items():
                and_.append({'term': {key: value}})
            for key, value in self.in_.items():
                and_.append({'in': {key: value}})
        elif self.filters:
            qs['filter'] = {'term': self.filters}
        elif self.in_:
            qs['filter'] = {'in': self.in_}

        if self.fields:
            qs['fields'] = self.fields
        if self.start:
            qs['from'] = self.start
        if self.stop:
            qs['size'] = self.stop - self.start
        if self.ordering:
            qs['sort'] = self.ordering

        return qs

    def _do_search(self):
        if not self._results_cache:
            qs = self._build_query()
            es = elasticutils.get_es()
            log.debug(qs)
            hits = es.search(qs, settings.ES_INDEX, self.type._meta.app_label)
            self._results_cache = SearchResults(self.type, hits)
        return self._results_cache

    def __iter__(self):
        return iter(self._do_search())


class SearchResults(object):

    def __init__(self, type, results):
        self.type = type
        self.took = results['took']
        statsd.timing('search', self.took)
        log.debug('Query took %dms.' % self.took)
        self.count = results['hits']['total']
        self.ids = [r['fields']['id'] for r in results['hits']['hits']]
        self.objects = self.type.objects.filter(id__in=self.ids)
        self.results = results

    def __iter__(self):
        objs = dict((obj.id, obj) for obj in self.objects)
        return (objs[id] for id in self.ids if id in objs)

    def __len__(self):
        return len(self.objects)
