import contextlib
import os
import time

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import models, transaction
from django.db.models.query import ModelIterable
from django.utils import translation

import elasticsearch
import multidb.pinning

import olympia.core.logger

from olympia.translations.hold import save_translations

from . import search


log = olympia.core.logger.getLogger('z.addons')


@contextlib.contextmanager
def use_master():
    """Within this context, all queries go to the master."""
    old = getattr(multidb.pinning._locals, 'pinned', False)
    multidb.pinning.pin_this_thread()
    try:
        yield
    finally:
        multidb.pinning._locals.pinned = old


class BaseQuerySet(models.QuerySet):

    def __init__(self, *args, **kwargs):
        super(BaseQuerySet, self).__init__(*args, **kwargs)
        self._transform_fns = []

    def _fetch_all(self):
        if self._result_cache is None:
            super(BaseQuerySet, self)._fetch_all()
            # At this point, _result_cache should have been filled up. If we
            # are dealing with a "regular" queryset (not values() etc) then we
            # call the transformers.
            if issubclass(self._iterable_class, ModelIterable):
                for func in self._transform_fns:
                    func(self._result_cache)

    def _clone(self, **kwargs):
        clone = super(BaseQuerySet, self)._clone(**kwargs)
        clone._transform_fns = self._transform_fns[:]
        return clone

    def transform(self, fn):
        clone = self._clone()
        clone._transform_fns.append(fn)
        return clone

    def pop_transforms(self):
        qs = self._clone()
        transforms = qs._transform_fns
        qs._transform_fns = []
        return transforms, qs

    def no_transforms(self):
        return self.pop_transforms()[1]

    def only_translations(self):
        """Remove all transforms except translations."""
        from olympia.translations import transformer
        # Add an extra select so these are cached separately.
        return (self.no_transforms().extra(select={'_only_trans': 1})
                .transform(transformer.get_trans))


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


class ManagerBase(models.Manager):
    """
    Base for all managers in AMO.

    Returns BaseQuerySets.

    If a model has translated fields, they'll be attached through a transform
    function.
    """
    _queryset_class = BaseQuerySet

    def get_queryset(self):
        qs = self._queryset_class(self.model, using=self._db)
        return self._with_translations(qs)

    def _with_translations(self, qs):
        from olympia.translations import transformer
        # Since we're attaching translations to the object, we need to stick
        # the locale in the query so objects aren't shared across locales.
        if hasattr(self.model._meta, 'translated_fields'):
            # We just add lang=lang in the query. We want to avoid NULL=NULL
            # though, so if lang is null we just add use dummy value instead.
            lang = translation.get_language() or '0'
            qs = qs.transform(transformer.get_trans)
            qs = qs.extra(where=['%s=%s'], params=[lang, lang])
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

        This should be replaced by "read committed" state:
        https://github.com/mozilla/addons-server/issues/7158
        """
        with transaction.atomic():
            try:
                return self.get(**kw), False
            except self.model.DoesNotExist:
                if defaults is not None:
                    kw.update(defaults)
                return self.create(**kw), True


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

            def watch_status(old_attr=None, new_attr=None,
                             instance=None, sender=None, **kwargs):
                if old_attr is None:
                    old_attr = {}
                if new_attr is None:
                    new_attr = {}
                if old_attr.get('status') != new_attr.get('status'):
                    # ...
                    new_instance.save(_signal=False)
            TheModel.on_change(watch_status)

        ``old_atr`` will be a dict of the old instance attributes.
        ``new_attr`` will be a dict of the new instance attributes, including
        any that had not been changed by the operation that triggered the
        callback (such as an update only of one field).

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
        id = str(id)
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


class SaveUpdateMixin(object):
    def reload(self):
        """Reloads the instance from the database."""
        from_db = self.__class__.get_unfiltered_manager().get(pk=self.pk)
        for field in self.__class__._meta.fields:
            try:
                setattr(self, field.name, getattr(from_db, field.name))
            except models.ObjectDoesNotExist:
                # reload() can be called before cleaning up an object of stale
                # related fields, when we do soft-deletion for instance. Avoid
                # failing because of that.
                pass
        return self

    @classmethod
    def get_unfiltered_manager(cls):
        """Return the unfiltered manager from the given class."""
        return getattr(cls, 'unfiltered', cls.objects)  # Fallback on objects.

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
        # We want this to not fail mysteriously for filtered out objects (eg
        # deleted or unlisted).
        objects = cls.get_unfiltered_manager()
        objects.filter(pk=self.pk).update(**kw)
        if signal:
            models.signals.post_save.send(sender=cls, instance=self,
                                          created=False)

    def save(self, **kwargs):
        # Unfortunately we have to save our translations before we call `save`
        # since Django verifies m2n relations with unsaved parent relations
        # and throws an error.
        # https://docs.djangoproject.com/en/1.9/topics/db/examples/one_to_one/
        if hasattr(self._meta, 'translated_fields'):
            save_translations(id(self))
        return super(SaveUpdateMixin, self).save(**kwargs)


class ModelBase(SearchMixin, SaveUpdateMixin, models.Model):
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

        # This is important: Setting this to `objects` makes sure
        # that Django is using the manager set as `objects` on this
        # instance reather than the `_default_manager` or even
        # `_base_manager`. That's the only way currently to reliably
        # tell Django to resolve translation objects / call transformers.
        # This also ensures we don't ignore soft-deleted items when traversing
        # relations, if they are hidden by the objects manager, like we
        # do with `addons.models:Addon`
        base_manager_name = 'objects'

    def get_absolute_url(self, *args, **kwargs):
        return self.get_url_path(*args, **kwargs)

    def serializable_reference(self):
        """Return a tuple with app label, model name and pk to be used when we
        need to pass a serializable reference to this instance without having
        to serialize the whole object."""
        return self._meta.app_label, self._meta.model_name, self.pk


def manual_order(qs, pks, pk_name='id'):
    """
    Given a query set and a list of primary keys, return a set of objects from
    the query set in that exact order.
    """
    if not pks:
        return qs.none()
    return qs.filter(id__in=pks).extra(
        select={'_manual': 'FIELD(%s, %s)' % (pk_name,
                                              ','.join(map(str, pks)))},
        order_by=['_manual'])


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


class BasePreview(object):
    thumbnail_url_template = 'thumbs/%s/%d.png?modified=%s'
    image_url_template = 'full/%s/%d.png?modified=%s'
    thumbnail_path_template = ('%s', 'thumbs', '%s', '%d.png')
    image_path_template = ('%s', 'full', '%s', '%d.png')
    original_path_template = ('%s', 'original', '%s', '%d.png')
    media_folder = 'previews'

    def _image_url(self, url_template):
        from olympia.amo.templatetags.jinja_helpers import user_media_url
        if self.modified is not None:
            modified = int(time.mktime(self.modified.timetuple()))
        else:
            modified = 0
        args = [self.id / 1000, self.id, modified]
        return user_media_url(self.media_folder) + url_template % tuple(args)

    def _image_path(self, url_template):
        from olympia.amo.templatetags.jinja_helpers import user_media_path
        args = [user_media_path(self.media_folder), self.id / 1000, self.id]
        return url_template % tuple(args)

    @property
    def thumbnail_url(self):
        return self._image_url(self.thumbnail_url_template)

    @property
    def image_url(self):
        return self._image_url(self.image_url_template)

    @property
    def thumbnail_path(self):
        return self._image_path(os.path.join(*self.thumbnail_path_template))

    @property
    def image_path(self):
        return self._image_path(os.path.join(*self.image_path_template))

    @property
    def original_path(self):
        return self._image_path(os.path.join(*self.original_path_template))

    @property
    def thumbnail_size(self):
        return self.sizes.get('thumbnail', []) if self.sizes else []

    @property
    def image_size(self):
        return self.sizes.get('image', []) if self.sizes else []

    @classmethod
    def delete_preview_files(cls, sender, instance, **kw):
        """On delete of the Preview object from the database, unlink the image
        and thumb on the file system """
        image_paths = [
            instance.image_path, instance.thumbnail_path,
            instance.original_path]
        for filename in image_paths:
            try:
                log.info('Removing filename: %s for preview: %s'
                         % (filename, instance.pk))
                storage.delete(filename)
            except Exception as e:
                log.error(
                    'Error deleting preview file (%s): %s' % (filename, e))
