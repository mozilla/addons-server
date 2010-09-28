import contextlib
import threading

from django.db import models
from django.utils import translation


import caching.base
import multidb.pinning
import queryset_transform
from translations import transformer

from . import signals


_locals = threading.local()
_locals.skip_cache = False


@contextlib.contextmanager
def use_master():
    """Within this context, all queries go to the master."""
    old = getattr(multidb.pinning._locals, 'pinned', False)
    multidb.pinning.pin_this_thread()
    try:
        yield
    finally:
        multidb.pinning._locals.pinned = old


@contextlib.contextmanager
def skip_cache():
    """Within this context, no queries come from cache."""
    old = getattr(_locals, 'skip_cache', False)
    _locals.skip_cache = True
    try:
        yield
    finally:
        _locals.skip_cache = old


class TransformQuerySet(queryset_transform.TransformQuerySet):

    def pop_transforms(self):
        qs = self._clone()
        transforms = qs._transform_fns
        qs._transform_fns = []
        return transforms, qs

    def no_transforms(self):
        return self.pop_transforms()[1]

    def only_translations(self):
        """Remove all transforms except translations."""
        # Add an extra select so these are cached separately.
        qs = self.no_transforms().extra(select={'_only_trans': 1})
        if hasattr(self.model._meta, 'translated_fields'):
            qs = qs.transform(transformer.get_trans)
        return qs

    def transform(self, fn):
        from . import decorators
        f = decorators.skip_cache(fn)
        return super(TransformQuerySet, self).transform(f)


class RawQuerySet(models.query.RawQuerySet):
    """A RawQuerySet with __len__."""

    def __init__(self, *args, **kw):
        super(RawQuerySet, self).__init__(*args, **kw)
        self._result_cache = None

    def __iter__(self):
        if self._result_cache is None:
            self._result_cache = list(super(RawQuerySet, self).__iter__())
        return iter(self._result_cache)

    def __len__(self):
        return len(list(self.__iter__()))


class CachingRawQuerySet(RawQuerySet, caching.base.CachingRawQuerySet):
    """A RawQuerySet with __len__ and caching."""

# Make TransformQuerySet one of CachingQuerySet's parents so that we can do
# transforms on objects and then get them cached.
CachingQuerySet = caching.base.CachingQuerySet
CachingQuerySet.__bases__ = (TransformQuerySet,) + CachingQuerySet.__bases__


class UncachedManagerBase(models.Manager):

    def get_query_set(self):
        qs = self._with_translations(TransformQuerySet(self.model))
        return qs

    def _with_translations(self, qs):
        # Since we're attaching translations to the object, we need to stick
        # the locale in the query so objects aren't shared across locales.
        if hasattr(self.model._meta, 'translated_fields'):
            lang = translation.get_language()
            qs = qs.transform(transformer.get_trans)
            qs = qs.extra(where=['"%s"="%s"' % (lang, lang)])
        return qs

    def transform(self, fn):
        return self.all().transform(fn)

    def raw(self, raw_query, params=None, *args, **kwargs):
        return RawQuerySet(raw_query, self.model, params=params,
                           using=self._db, *args, **kwargs)


class ManagerBase(caching.base.CachingManager, UncachedManagerBase):
    """
    Base for all managers in AMO.

    Returns TransformQuerySets from the queryset_transform project.

    If a model has translated fields, they'll be attached through a transform
    function.
    """

    def get_query_set(self):
        qs = super(ManagerBase, self).get_query_set()
        if getattr(_locals, 'skip_cache', False):
            qs = qs.no_cache()
        return self._with_translations(qs)

    def raw(self, raw_query, params=None, *args, **kwargs):
        return CachingRawQuerySet(raw_query, self.model, params=params,
                                  using=self._db, *args, **kwargs)


class ModelBase(caching.base.CachingMixin, models.Model):
    """
    Base class for AMO models to abstract some common features.

    * Adds automatic created and modified fields to the model.
    * Fetches all translations in one subsequent query during initialization.
    """

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = ManagerBase()
    uncached = UncachedManagerBase()

    class Meta:
        abstract = True
        get_latest_by = 'created'

    def get_absolute_url(self, *args, **kwargs):
        return self.get_url_path(*args, **kwargs)

    def update(self, **kw):
        """
        Shortcut for doing an UPDATE on this object.

        If _signal=False is in ``kw`` the post_save signal won't be sent.
        """
        signal = kw.pop('_signal', True)
        cls = self.__class__
        cls.objects.filter(pk=self.pk).update(**kw)
        for k, v in kw.items():
            setattr(self, k, v)
        if signal:
            models.signals.post_save.send(sender=cls, instance=self,
                                          created=False)


def manual_order(qs, pks, pk_name='id'):
    """
    Given a query set and a list of primary keys, return a set of objects from
    the query set in that exact order.
    """

    if not pks:
        return []

    objects = qs.filter(id__in=pks).extra(
            select={'_manual': 'FIELD(%s, %s)'
                % (pk_name, ','.join(map(str, pks)))},
            order_by=['_manual'])

    return objects
