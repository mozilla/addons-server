"""
To enable caching for a model, add the :class:`~caching.CachingManager` to that
class and inherit from the :class:`~caching.CachingMixin`.  If you want related
(foreign key) lookups to hit the cache, ``CachingManager`` must be the default
manager.  If you have multiple managers that should be cached, return a
:class:`~caching.CachingQuerySet` from the other manager's ``get_query_set``
method instead of subclassing ``CachingManager``, since that would hook up the
post_save and post_delete signals multiple times.

Here's what a minimal cached model looks like::

    from django.db import models

    import caching

    class Zomg(caching.CachingMixin, models.Model):
        val = models.IntegerField()

        objects = caching.CachingManager()

Whenever you run a query, ``CachingQuerySet`` will try to find that query in
the cache.  Queries are keyed by ``{locale}:{sql}``. If it's there, we return
the cached result set and everyone is happy.  If the query isn't in the cache,
the normal codepath to run a database query is executed.  As the objects in the
result set are iterated over, they are added to a list that will get cached
once iteration is done.

.. note::
    Nothing will be cached if the QuerySet is not iterated through completely.

To support easy cache invalidation, we use "flush lists" to mark the cached
queries an object belongs to.  That way, all queries where an object was found
will be invalidated when that object changes.  Flush lists map an object key to
a list of query keys.

When an object is saved or deleted, all query keys in its flush list will be
deleted.  In addition, the flush lists of its foreign key relations will be
cleared.  To avoid stale foreign key relations, any cached objects will be
flushed when the object their foreign key points to is invalidated.

During cache invalidation, we explicitly set a None value instead of just
deleting so we don't have any race condtions where:

 * Thread 1 -> Cache miss, get object from DB
 * Thread 2 -> Object saved, deleted from cache
 * Thread 1 -> Store (stale) object fetched from DB in cache

The foundations of this module were derived from `Mike Malone's`_
`django-caching`_.

.. _`Mike Malone's`: http://immike.net/
.. _django-caching: http://github.com/mmalone/django-caching/
"""

import hashlib
import logging

from django.conf import settings
from django.db import models
from django.db.models import signals
from django.db.models.sql import query
from django.utils import translation, encoding

from .backends import cache

FOREVER = 0

log = logging.getLogger('z.caching')


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
        log.debug('post_save signal for %s' % instance)
        self.invalidate(instance)

    def post_delete(self, instance, **kwargs):
        log.debug('post_delete signal for %s' % instance)
        self.invalidate(instance)

    def invalidate(self, *objects):
        """Invalidate all the flush lists associated with ``objects``."""
        self.invalidate_keys(k for o in objects for k in o._cache_keys())

    def invalidate_keys(self, keys):
        """Invalidate all the flush lists named by the list of ``keys``."""
        keys = map(flush_key, keys)

        # Add other flush keys from the lists, which happens when a parent
        # object includes a foreign key.
        for flush_list in cache.get_many(*keys):
            if flush_list is not None:
                keys.extend(k for k in flush_list if k.startswith('flush:'))

        flush = []
        for flush_list in cache.get_many(*keys):
            if flush_list is not None:
                flush.extend(flush_list)
        log.debug('invalidating %s' % keys)
        log.debug('flushing %s' % flush)
        cache.set_many(dict((k, None) for k in flush), 5)
        cache.delete_many(*keys)


class CachingQuerySet(models.query.QuerySet):

    def iterator(self):
        try:
            query_key = self._query_key()
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
        superiter = super(CachingQuerySet, self).iterator()

        to_cache = []
        try:
            while True:
                obj = superiter.next()
                obj.from_cache = False
                to_cache.append(obj)
                yield obj
        except StopIteration:
            self._cache_objects(to_cache)
            raise

    def _query_key(self):
        """Generate a cache key for this QuerySet."""
        lang = translation.get_language()
        key = '%s:%s' % (lang, self.query)
        # memcached keys must be < 250 bytes and w/o whitespace, but it's nice
        # to see the keys when using locmem.
        if cache.scheme == 'memcached':
            return '%s%s' % (settings.CACHE_PREFIX,
                             hashlib.md5(key).hexdigest())
        else:
            return '%s%s' % (settings.CACHE_PREFIX, key)

    def _cache_objects(self, objects):
        """Cache query_key => objects, then update the flush lists."""
        # Adding to the flush lists has a race condition: if simultaneous
        # processes are adding to the same list, one of the query keys will be
        # dropped.  Using redis would be safer.

        def add_to_flush_list(flush_keys, new_key):
            """Add new_key to all the flush lists keyed by flush_keys."""
            flush_lists = cache.get_dict(*flush_keys)
            for key, list_ in flush_lists.items():
                if list_ is None:
                    flush_lists[key] = [new_key]
                else:
                    list_.append(new_key)
            cache.set_many(flush_lists)

        query_key = self._query_key()

        cache.add(query_key, objects, settings.CACHE_DURATION)

        flush_keys = map(flush_key, objects)
        add_to_flush_list(flush_keys, query_key)

        for obj in objects:
            obj_flush = flush_key(obj)
            keys = map(flush_key, obj._cache_keys())
            keys.remove(obj_flush)
            add_to_flush_list(keys, obj_flush)


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
