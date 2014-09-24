import contextlib
import threading

from django.conf import settings
from django.db import models, transaction
from django.utils import encoding, translation

import caching.base
import elasticsearch
import multidb.pinning
import queryset_transform

from . import search
from . import signals  # Needed to set up url prefix signals.


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


# This is sadly a copy and paste of annotate to get around this
# ticket http://code.djangoproject.com/ticket/14707
def annotate(self, *args, **kwargs):

    for arg in args:
        if arg.default_alias in kwargs:
            raise ValueError("The %s named annotation conflicts with the "
                             "default name for another annotation."
                             % arg.default_alias)
        kwargs[arg.default_alias] = arg

    obj = self._clone()

    obj._setup_aggregate_query(kwargs.keys())

    # Add the aggregates to the query
    for (alias, aggregate_expr) in kwargs.items():
        obj.query.add_aggregate(aggregate_expr, self.model, alias,
            is_summary=False)

    return obj

models.query.QuerySet.annotate = annotate


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
        from translations import transformer
        # Add an extra select so these are cached separately.
        return (self.no_transforms().extra(select={'_only_trans': 1})
                .transform(transformer.get_trans))

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
        from translations import transformer
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

    def safer_get_or_create(self, defaults=None, **kw):
        """
        This is subjective, but I don't trust get_or_create until #13906
        gets fixed. It's probably fine, but this makes me happy for the moment
        and solved a get_or_create we've had in the past.
        """
        with transaction.commit_on_success():
            try:
                return self.get(**kw), False
            except self.model.DoesNotExist:
                if defaults is not None:
                    kw.update(defaults)
                return self.create(**kw), True


class ManagerBase(caching.base.CachingManager, UncachedManagerBase):
    """
    Base for all managers in AMO.

    Returns TransformQuerySets from the queryset_transform project.

    If a model has translated fields, they'll be attached through a transform
    function.
    """

    def get_queryset(self):
        qs = super(ManagerBase, self).get_queryset()
        if getattr(_locals, 'skip_cache', False):
            qs = qs.no_cache()
        return self._with_translations(qs)

    def raw(self, raw_query, params=None, *args, **kwargs):
        return CachingRawQuerySet(raw_query, self.model, params=params,
                                  using=self._db, *args, **kwargs)


class _NoChangeInstance(object):
    """A proxy for object instances to make safe operations within an
    OnChangeMixin.on_change() callback.
    """

    def __init__(self, instance):
        self.__instance = instance

    def __repr__(self):
        return u'<%s for %r>' % (self.__class__.__name__, self.__instance)

    def __getattr__(self, attr):
        return getattr(self.__instance, attr)

    def __setattr__(self, attr, val):
        if attr.endswith('__instance'):
            # _NoChangeInstance__instance
            self.__dict__[attr] = val
        else:
            setattr(self.__instance, attr, val)

    def save(self, *args, **kw):
        kw['_signal'] = False
        return self.__instance.save(*args, **kw)

    def update(self, *args, **kw):
        kw['_signal'] = False
        return self.__instance.update(*args, **kw)


_on_change_callbacks = {}


# @TODO(Kumar) liberate: move OnChangeMixin Model mixin to nuggets
class OnChangeMixin(object):
    """Mixin for a Model that allows you to observe attribute changes.

    Register change observers with::

        class YourModel(amo.models.OnChangeMixin,
                        amo.models.ModelBase):
            # ...
            pass

        YourModel.on_change(callback)

    """

    def __init__(self, *args, **kw):
        super(OnChangeMixin, self).__init__(*args, **kw)
        self._initial_attr = dict(self.__dict__)

    @classmethod
    def on_change(cls, callback):
        """Register a function to call on save or update to respond to changes.

        For example::

            def watch_status(old_attr={}, new_attr={},
                             instance=None, sender=None, **kw):
                if old_attr.get('status') != new_attr.get('status'):
                    # ...
                    new_instance.save(_signal=False)
            TheModel.on_change(watch_status)

        .. note::

            Any call to instance.save() or instance.update() within a callback
            will not trigger any change handlers.

        .. note::

            Duplicates based on function.__name__ are ignored for a given
            class.
        """
        existing = _on_change_callbacks.get(cls, [])
        if callback.__name__ in [e.__name__ for e in existing]:
            return callback

        _on_change_callbacks.setdefault(cls, []).append(callback)
        return callback

    def _send_changes(self, old_attr, new_attr_kw):
        new_attr = old_attr.copy()
        new_attr.update(new_attr_kw)
        for cb in _on_change_callbacks[self.__class__]:
            cb(old_attr=old_attr, new_attr=new_attr,
               instance=_NoChangeInstance(self), sender=self.__class__)

    def save(self, *args, **kw):
        """
        Save changes to the model instance.

        If _signal=False is in `kw` the on_change() callbacks won't be called.
        """
        signal = kw.pop('_signal', True)
        result = super(OnChangeMixin, self).save(*args, **kw)
        if signal and self.__class__ in _on_change_callbacks:
            self._send_changes(self._initial_attr, dict(self.__dict__))
        return result

    def update(self, **kw):
        """
        Shortcut for doing an UPDATE on this object.

        If _signal=False is in ``kw`` the post_save signal won't be sent.
        """
        signal = kw.pop('_signal', True)
        old_attr = dict(self.__dict__)
        result = super(OnChangeMixin, self).update(_signal=signal, **kw)
        if signal and self.__class__ in _on_change_callbacks:
            self._send_changes(old_attr, kw)
        return result


class SearchMixin(object):

    ES_ALIAS_KEY = 'default'

    @classmethod
    def _get_index(cls):
        indexes = settings.ES_INDEXES
        return indexes.get(cls.ES_ALIAS_KEY)

    @classmethod
    def index(cls, document, id=None, refresh=False, index=None):
        """Wrapper around Elasticsearch.index."""
        search.get_es().index(
            body=document, index=index or cls._get_index(),
            doc_type=cls.get_mapping_type(), id=id, refresh=refresh)

    @classmethod
    def unindex(cls, id, index=None):
        es = search.get_es()
        try:
            es.delete(index or cls._get_index(), cls._meta.db_table, id)
        except elasticsearch.TransportError:
            # Item wasn't found, whatevs.
            pass

    @classmethod
    def search(cls, index=None):
        return search.ES(cls, index or cls._get_index())

    @classmethod
    def get_mapping_type(cls):
        return cls._meta.db_table


class ModelBase(SearchMixin, caching.base.CachingMixin, models.Model):
    """
    Base class for AMO models to abstract some common features.

    * Adds automatic created and modified fields to the model.
    * Fetches all translations in one subsequent query during initialization.
    """

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = ManagerBase()

    class Meta:
        abstract = True
        get_latest_by = 'created'

    def get_absolute_url(self, *args, **kwargs):
        return self.get_url_path(*args, **kwargs)

    @classmethod
    def _cache_key(cls, pk, db):
        """
        Custom django-cache-machine cache key implementation that avoids having
        the real db in the key, since we are only using master-slaves we don't
        need it and it avoids invalidation bugs with FETCH_BY_ID.
        """
        key_parts = ('o', cls._meta, pk, 'default')
        return ':'.join(map(encoding.smart_unicode, key_parts))

    def reload(self):
        """Reloads the instance from the database."""
        from_db = self.__class__.objects.get(id=self.id)
        for field in self.__class__._meta.fields:
            try:
                setattr(self, field.name, getattr(from_db, field.name))
            except models.ObjectDoesNotExist:
                # reload() can be called before cleaning up an object of stale
                # related fields, when we do soft-deletion for instance. Avoid
                # failing because of that.
                pass
        return self

    def update(self, **kw):
        """
        Shortcut for doing an UPDATE on this object.

        If _signal=False is in ``kw`` the post_save signal won't be sent.
        """
        signal = kw.pop('_signal', True)
        cls = self.__class__
        for k, v in kw.items():
            setattr(self, k, v)
        if signal:
            # Detect any attribute changes during pre_save and add those to the
            # update kwargs.
            attrs = dict(self.__dict__)
            models.signals.pre_save.send(sender=cls, instance=self)
            for k, v in self.__dict__.items():
                if attrs[k] != v:
                    kw[k] = v
                    setattr(self, k, v)
        cls.objects.filter(pk=self.pk).update(**kw)
        if signal:
            models.signals.post_save.send(sender=cls, instance=self,
                                          created=False)


def manual_order(qs, pks, pk_name='id'):
    """
    Given a query set and a list of primary keys, return a set of objects from
    the query set in that exact order.
    """
    if not pks:
        return qs.none()
    return qs.filter(id__in=pks).extra(
            select={'_manual': 'FIELD(%s, %s)'
                % (pk_name, ','.join(map(str, pks)))},
            order_by=['_manual'])


class BlobField(models.Field):
    """MySQL blob column.

    This is for using AES_ENCYPT() to store values.
    It could maybe turn into a fancy transparent encypt/decrypt field
    like http://djangosnippets.org/snippets/2489/
    """
    description = "blob"

    def db_type(self, **kw):
        return 'blob'


class SlugField(models.SlugField):
    """
    Django 1.6's SlugField rejects non-ASCII slugs. This field just
    keeps the old behaviour of not checking contents.
    """
    default_validators = []


class FakeEmail(ModelBase):
    message = models.TextField()

    class Meta:
        db_table = 'fake_email'
