import hashlib
import logging

from django.conf import settings
from django.core.cache import cache, parse_backend_uri
from django.db import models
from django.db.models import signals
from django.db.models.sql import query
from django.utils import translation, encoding

FOREVER = 0

log = logging.getLogger('z.caching')

scheme, _, _ = parse_backend_uri(settings.CACHE_BACKEND)
cache.scheme = scheme


class CachingManager(models.Manager):

    # Tell Django to use this manager when resolving foreign keys.
    use_for_related_fields = True

    def get_query_set(self):
        return CachingQuerySet(self.model)

    def contribute_to_class(self, cls, name):
        signals.post_save.connect(self.post_save, sender=cls)
        signals.post_delete.connect(self.post_delete, sender=cls)
        return super(CachingManager, self).contribute_to_class(cls, name)

    def post_save(self, instance, **kwargs):
        self.invalidate(instance)

    def post_delete(self, instance, **kwargs):
        self.invalidate(instance)

    def invalidate(self, *objects):
        """Invalidate all the flush lists associated with ``objects``."""
        self.invalidate_keys(k for o in objects for k in o._cache_keys())

    def invalidate_keys(self, keys):
        """Invalidate all the flush lists named by the list of ``keys``."""
        keys = set(map(flush_key, keys))

        # Add other flush keys from the lists, which happens when a parent
        # object includes a foreign key.
        for flush_list in cache.get_many(keys).values():
            if flush_list is not None:
                keys.update(k for k in flush_list if k.startswith('flush:'))

        flush = set()
        for flush_list in cache.get_many(set(keys)).values():
            if flush_list is not None:
                flush.update(flush_list)
        log.debug('invalidating %s' % keys)
        log.debug('flushing %s' % flush)
        cache.set_many(dict((k, None) for k in flush), 5)
        cache.delete_many(keys)

    def raw(self, raw_query, params=None, *args, **kwargs):
        return CachingRawQuerySet(raw_query, self.model, params=params,
                                  using=self._db, *args, **kwargs)


class CacheMachine(object):
    """
    Handles all the cache management for a QuerySet.

    Takes the string representation of a query and a function that can be
    called to get an iterator over some database results.
    """

    def __init__(self, query_string, iter_function):
        self.query_string = query_string
        self.iter_function = iter_function

    def query_key(self):
        """Generate the cache key for this query."""
        key = '%s:%s' % (translation.get_language(), self.query_string)

        # memcached keys must be < 250 bytes and w/o whitespace, but it's nice
        # to see the keys when using locmem.
        if 'memcached' in cache.scheme:
            return '%s%s' % (settings.CACHE_PREFIX,
                             hashlib.md5(key).hexdigest())
        else:
            return '%s%s' % (settings.CACHE_PREFIX, key)

    def __iter__(self):
        try:
            query_key = self.query_key()
        except query.EmptyResultSet:
            raise StopIteration

        # Try to fetch from the cache.
        cached = cache.get(query_key)
        if cached is not None:
            log.debug('cache hit: %s' % query_key)
            for obj in cached:
                obj.from_cache = True
                yield obj
            return

        # Do the database query, cache it once we have all the objects.
        iterator = self.iter_function()

        to_cache = []
        try:
            while True:
                obj = iterator.next()
                obj.from_cache = False
                to_cache.append(obj)
                yield obj
        except StopIteration:
            self.cache_objects(to_cache)
            raise

    def cache_objects(self, objects):
        """Cache query_key => objects, then update the flush lists."""
        # Adding to the flush lists has a race condition: if simultaneous
        # processes are adding to the same list, one of the query keys will be
        # dropped.  Using redis would be safer.

        def add_to_flush_list(flush_keys, new_key):
            """Add new_key to all the flush lists keyed by flush_keys."""
            flush_lists = dict((key, None) for key in flush_keys)
            flush_lists.update(cache.get_many(flush_keys))
            for key, list_ in flush_lists.items():
                if list_ is None:
                    flush_lists[key] = [new_key]
                else:
                    list_.append(new_key)
            cache.set_many(flush_lists)

        query_key = self.query_key()

        cache.add(query_key, objects, settings.CACHE_DURATION)

        flush_keys = map(flush_key, objects)
        add_to_flush_list(flush_keys, query_key)

        for obj in objects:
            obj_flush = flush_key(obj)
            keys = map(flush_key, obj._cache_keys())
            keys.remove(obj_flush)
            add_to_flush_list(keys, obj_flush)


class CachingQuerySet(models.query.QuerySet):

    def iterator(self):
        # Work-around for Django #12717.
        sql, params = self.query.get_compiler(using=self.db).as_sql()
        query_string = sql % params
        iterator = super(CachingQuerySet, self).iterator
        for obj in CacheMachine(query_string, iterator):
            yield obj
        raise StopIteration


def flush_key(obj):
    """We put flush lists in the flush: namespace."""
    key = obj if isinstance(obj, basestring) else obj.cache_key
    return 'flush:%s' % key


class CachingMixin:
    """Inherit from this class to get caching and invalidation helpers."""

    @property
    def cache_key(self):
        """Return a cache key based on the object's primary key."""
        return self._cache_key(self.pk)

    @classmethod
    def _cache_key(cls, pk):
        """
        Return a string that uniquely identifies the object.

        For the Addon class, with a pk of 2, we get "o:addons.addon:2".
        """
        key_parts = ('o', cls._meta, pk)
        return ':'.join(map(encoding.smart_unicode, key_parts))

    def _cache_keys(self):
        """Return the cache key for self plus all related foreign keys."""
        fks = dict((f, getattr(self, f.attname)) for f in self._meta.fields
                    if isinstance(f, models.ForeignKey))

        keys = [fk.rel.to._cache_key(val) for fk, val in fks.items()
                if val is not None and hasattr(fk.rel.to, '_cache_key')]
        return (self.cache_key,) + tuple(keys)


class CachingRawQuerySet(models.query.RawQuerySet):

    def __iter__(self):
        iterator = super(CachingRawQuerySet, self).__iter__
        for obj in CacheMachine(self.raw_query, iterator):
            yield obj
        raise StopIteration
