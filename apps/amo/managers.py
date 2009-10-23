"""
CachingManager  from
http://github.com/mmalone/django-caching/blob/master/app/managers.py,
with fixes to cache on more than primary key.
"""

from django.db import models
from django.db.models import signals
from django.db.models.query import QuerySet
from django.core.cache import cache

CACHE_DURATION = 60 * 30

def _cache_key(model, **fields):
    key = ':'.join('%s=%s' % item for item in sorted(fields.items()))
    return '%s.%s.%s' % (model._meta.app_label, model._meta.module_name, key)


def _get_cache_key(self, field=None):
    return self._cache_key(pk=self.pk)


class CachingManager(models.Manager):
    def __init__(self, use_for_related_fields=True, *args, **kwargs):
        self.use_for_related_fields = use_for_related_fields
        super(CachingManager, self).__init__(*args, **kwargs)

    def get_query_set(self):
        return CachingQuerySet(self.model)

    def contribute_to_class(self, model, name):
        signals.post_save.connect(self._post_save, sender=model)
        signals.post_delete.connect(self._post_delete, sender=model)
        setattr(model, '_cache_key', classmethod(_cache_key))
        setattr(model, '_get_cache_key', _get_cache_key)
        if not hasattr(model, 'cache_key'):
            setattr(model, 'cache_key', property(_get_cache_key))
        return super(CachingManager, self).contribute_to_class(model, name)

    def _invalidate_cache(self, instance):
        """
        Explicitly set a None value instead of just deleting so we don't have any race
        conditions where:
            Thread 1 -> Cache miss, get object from DB
            Thread 2 -> Object saved, deleted from cache
            Thread 1 -> Store (stale) object fetched from DB in cache
        Five second should be more than enough time to prevent this from happening for
        a web app.
        """
        cache.set(instance.cache_key, None, 5)

    def _post_save(self, instance, **kwargs):
        self._invalidate_cache(instance)

    def _post_delete(self, instance, **kwargs):
        self._invalidate_cache(instance)


class CachingQuerySet(QuerySet):
    def iterator(self):
        superiter = super(CachingQuerySet, self).iterator()
        while True:
            obj = superiter.next()
            # Use cache.add instead of cache.set to prevent race conditions (see CachingManager)
            cache.add(obj.cache_key, obj, CACHE_DURATION)
            print 'added', obj.cache_key
            yield obj

    def get(self, *args, **kwargs):
        """
        Checks the cache to see if there's a cached entry for this pk. If not, fetches
        using super then stores the result in cache.

        Most of the logic here was gathered from a careful reading of
        ``django.db.models.sql.query.add_filter``
        """
        if self.query.where:
            # If there is any other ``where`` filter on this QuerySet just call
            # super. There will be a where clause if this QuerySet has already
            # been filtered/cloned.
            return super(CachingQuerySet, self).get(*args, **kwargs)

        print 'trying', self.model._cache_key(**kwargs)
        obj = cache.get(self.model._cache_key(**kwargs))
        if obj is not None:
            print 'cache hit!', self.model._cache_key(**kwargs)
            obj.from_cache = True
            return obj

        # Calls self.iterator to fetch objects, storing object in cache.
        return super(CachingQuerySet, self).get(*args, **kwargs)
