import contextlib
import os
import time
from urllib.parse import urljoin

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import models
from django.db.models import Lookup
from django.db.models.expressions import Func
from django.db.models.fields import CharField, Field
from django.db.models.fields.related_descriptors import ManyToManyDescriptor
from django.db.models.query import ModelIterable
from django.urls import resolve, reverse
from django.urls.exceptions import Resolver404
from django.utils import timezone, translation
from django.utils.functional import cached_property

import multidb.pinning

import olympia.core.logger
from olympia.translations.hold import save_translations


log = olympia.core.logger.getLogger('z.addons')


@Field.register_lookup
class Like(Lookup):
    lookup_name = 'like'

    def as_sql(self, compiler, connection):
        lhs_sql, params = self.process_lhs(compiler, connection)
        rhs_sql, rhs_params = self.process_rhs(compiler, connection)
        params.extend(rhs_params)
        # This looks scarier than it is: rhs_sql should to resolve to '%s',
        # lhs_sql to the query before this part. The params are isolated and
        # will be passed to the database client code separately, ensuring
        # everything is escaped correctly.
        return '%s LIKE %s' % (lhs_sql, rhs_sql), params


@contextlib.contextmanager
def use_primary_db():
    """Within this context, all queries go to the master."""
    old = getattr(multidb.pinning._locals, 'pinned', False)
    multidb.pinning.pin_this_thread()
    try:
        yield
    finally:
        multidb.pinning._locals.pinned = old


class BaseQuerySet(models.QuerySet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._transform_fns = []

    def _fetch_all(self):
        if self._result_cache is None:
            super()._fetch_all()
            # At this point, _result_cache should have been filled up. If we
            # are dealing with a "regular" queryset (not values() etc) then we
            # call the transformers.
            if issubclass(self._iterable_class, ModelIterable):
                for func in self._transform_fns:
                    func(self._result_cache)

    def _clone(self, **kwargs):
        clone = super()._clone(**kwargs)
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
        qs = self.no_transforms()
        if hasattr(self.model._meta, 'translated_fields'):
            qs = qs.transform(transformer.get_trans)
        return qs


class RawQuerySet(models.query.RawQuerySet):
    """A RawQuerySet with __len__."""

    def __init__(self, raw_query, *args, **kw):
        super().__init__(raw_query, *args, **kw)
        self._result_cache = None

    def __iter__(self):
        if self._result_cache is None:
            self._result_cache = list(super().__iter__())
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
        from django.db.models import Value

        from olympia.translations import transformer

        if hasattr(self.model._meta, 'translated_fields'):
            qs = qs.transform(transformer.get_trans)
            # Annotate the queryset with the current language to prevent any
            # caching of the query to share results across languages.
            qs = qs.annotate(
                __lang=Value(translation.get_language() or '', output_field=CharField())
            )
        return qs

    def transform(self, fn):
        return self.all().transform(fn)

    def raw(self, raw_query, params=(), translations=None, using=None):
        return RawQuerySet(
            raw_query,
            model=self.model,
            params=params,
            translations=translations,
            using=using or self._db,
        )


class _NoChangeInstance:
    """A proxy for object instances to make safe operations within an
    OnChangeMixin.on_change() callback.
    """

    def __init__(self, instance):
        self.__instance = instance

    def __repr__(self):
        return f'<{self.__class__.__name__} for {self.__instance!r}>'

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


class OnChangeMixin:
    """Mixin for a Model that allows you to observe attribute changes.

    Register change observers with::

        class YourModel(amo.models.OnChangeMixin,
                        amo.models.ModelBase):
            # ...
            pass

        YourModel.on_change(callback)

    """

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._reset_initial_attrs()

    def _reset_initial_attrs(self, attrs=None):
        if attrs is None:
            self._initial_attrs = {
                k: v
                for k, v in self.__dict__.items()
                if k not in ('_state', '_initial_attrs')
            }
        else:
            self._initial_attrs.update(attrs)

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
            cb(
                old_attr=old_attr,
                new_attr=new_attr,
                instance=_NoChangeInstance(self),
                sender=self.__class__,
            )

    def save(self, *args, **kwargs):
        """
        Save changes to the model instance.

        If _signal=False is in `kw` the on_change() callbacks won't be called.
        """
        # When saving an existing instance, if the caller didn't specify
        # an explicit update_fields and _dynamic_update_fields is absent or
        # True, we attempt to find out which fields were changed and only
        # save those. This allows for slightly better performance as we don't
        # keep re-saving the same data over and over again, but also avoids
        # overwriting data that has changed in the meantime.
        # Fields with auto_now=True will be included all the time.
        #
        # Note that deferred fields will be included in the list of changed
        # fields if they are loaded afterwards, even if their value does not
        # change.
        if (
            self.pk
            # Just having self.pk is not enough, we only really want to catch
            # UPDATE calls and the caller could be doing Model(pk=1).save().
            # Django save() implementation uses the special _state attribute
            # for this.
            and self._state.adding is False
            and kwargs.get('update_fields') is None
            and kwargs.pop('_dynamic_update_fields', True)
        ):
            fields = [f.attname for f in self._meta.concrete_fields]
            concrete_initial_attrs = [
                (k, v) for k, v in self._initial_attrs.items() if k in fields
            ]
            current_attrs = [(k, self.__dict__[k]) for k, v in concrete_initial_attrs]
            changed_attrs = (
                set(current_attrs)
                - set(concrete_initial_attrs)
                # Never include primary key field - it might be set to None
                # initially in _initial_attrs right after a call to create()
                # even though self.pk is set.
                - {(self._meta.pk.name, self.pk)}
            )
            auto_now_fields = [
                f.name for f in self._meta.fields if getattr(f, 'auto_now', False)
            ]
            kwargs['update_fields'] = [k for k, v in changed_attrs] + auto_now_fields
        signal = kwargs.pop('_signal', True)
        result = super().save(*args, **kwargs)
        if signal and self.__class__ in _on_change_callbacks:
            self._send_changes(self._initial_attrs.copy(), dict(self.__dict__))
        # Reset initial_attr to be ready for the next save.
        updated_fields = kwargs.get('update_fields')
        self._reset_initial_attrs(
            attrs={k: self.__dict__[k] for k in updated_fields}
            if updated_fields
            else None
        )
        return result

    def update(self, **kwargs):
        """
        Shortcut for doing an UPDATE on this object.

        If _signal=False is in ``kwargs`` the post_save signal won't be sent.
        """
        signal = kwargs.pop('_signal', True)
        old_attr = dict(self.__dict__)
        result = super().update(_signal=signal, **kwargs)
        if signal and self.__class__ in _on_change_callbacks:
            self._send_changes(old_attr, kwargs)
        # Reset initial_attr to be ready for the next save. We only reset the
        # fields we changed however, because the rest hasn't been saved yet.
        # Otherwise doing obj.foo = 'bar' followed by obj.update(plop=42) and
        # then obj.save() wouldn't save `foo`, because we'd reset the attrs
        # used to compare in the .update() call.
        self._reset_initial_attrs(attrs=kwargs)
        return result


class SaveUpdateMixin:
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
            models.signals.post_save.send(sender=cls, instance=self, created=False)

    def save(self, **kwargs):
        # Unfortunately we have to save our translations before we call `save`
        # since Django verifies m2n relations with unsaved parent relations
        # and throws an error.
        # https://docs.djangoproject.com/en/1.9/topics/db/examples/one_to_one/
        if hasattr(self._meta, 'translated_fields'):
            save_translations(self)
        return super().save(**kwargs)


class ModelBase(SaveUpdateMixin, models.Model):
    """
    Base class for AMO models to abstract some common features.

    * Adds automatic created and modified fields to the model.
    * Fetches all translations in one subsequent query during initialization.
    """

    created = models.DateTimeField(default=timezone.now, editable=False, blank=True)
    modified = models.DateTimeField(auto_now=True)

    objects = ManagerBase()

    class Meta:
        abstract = True
        get_latest_by = 'created'
        # This is important: Setting this to `objects` makes sure
        # that Django is using the manager set as `objects` on this
        # instance reather than the `_default_manager` or even
        # `_base_manager` that are by default configured by Django.
        # That's the only way currently to reliably tell Django to resolve
        # translation objects / call transformers.
        # This also ensures we don't ignore soft-deleted items when traversing
        # relations, if they are hidden by the objects manager, like we
        # do with `addons.models:Addon`
        base_manager_name = 'objects'

    def get_absolute_url(self, *args, **kwargs):
        relative_url = self.get_url_path(*args, **kwargs)
        try:
            func = resolve(relative_url).func
            is_frontend = getattr(func, 'is_frontend_view', False)
        except Resolver404:
            is_frontend = False
        site = settings.EXTERNAL_SITE_URL if is_frontend else settings.SITE_URL
        return urljoin(site, relative_url)

    def get_admin_url_path(self):
        """
        Return the relative URL pointing to the instance admin change page.
        """
        urlname = f'admin:{self._meta.app_label}_{self._meta.model_name}_change'
        return reverse(urlname, args=(self.pk,))

    def get_admin_absolute_url(self):
        """
        Return the absolute URL pointing to the instance admin change page.
        """
        return urljoin(settings.SITE_URL, self.get_admin_url_path())

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
        select={'_manual': 'FIELD({}, {})'.format(pk_name, ','.join(map(str, pks)))},
        order_by=['_manual'],
    )


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


class BasePreview:
    media_folder = 'previews'

    def _image_url(self, folder, file_ext):
        modified = int(time.mktime(self.modified.timetuple())) if self.modified else 0

        url = '/'.join(
            (
                folder,
                str(self.id // 1000),
                f'{self.id}.{file_ext}?modified={modified}',
            )
        )
        return f'{settings.MEDIA_URL}{self.media_folder}/{url}'

    def _image_path(self, folder, file_ext):
        url = os.path.join(
            settings.MEDIA_ROOT,
            self.media_folder,
            folder,
            str(self.id // 1000),
            f'{self.id}.{file_ext}',
        )
        return url

    @property
    def thumbnail_url(self):
        return self._image_url('thumbs', self.get_format('thumbnail'))

    @property
    def image_url(self):
        return self._image_url('full', self.get_format('image'))

    @property
    def thumbnail_path(self):
        return self._image_path('thumbs', self.get_format('thumbnail'))

    @property
    def image_path(self):
        return self._image_path('full', self.get_format('image'))

    @property
    def original_path(self):
        return self._image_path('original', self.get_format('original'))

    @property
    def thumbnail_dimensions(self):
        return self.sizes.get('thumbnail', []) if self.sizes else []

    @property
    def image_dimensions(self):
        return self.sizes.get('image', []) if self.sizes else []

    def get_format(self, for_size):
        return self.sizes.get(f'{for_size}_format', 'png')

    @classmethod
    def delete_preview_files(cls, sender, instance, **kw):
        """On delete of the Preview object from the database, unlink the image
        and thumb on the file system"""
        image_paths = [
            instance.image_path,
            instance.thumbnail_path,
            instance.original_path,
        ]
        for filename in image_paths:
            try:
                log.info(f'Removing filename: {filename} for preview: {instance.pk}')
                storage.delete(filename)
            except Exception as e:
                log.error(f'Error deleting preview file ({filename}): {e}')


class LongNameIndex(models.Index):
    """Django's Index, but with a longer allowed name since we don't care about
    compatibility with Oracle."""

    max_name_length = 64  # Django default is 30, but MySQL can go up to 64.


class FilterableManyToManyDescriptor(ManyToManyDescriptor):
    def __init__(self, *args, **kwargs):
        self.q_filter = kwargs.pop('q_filter', None)
        super().__init__(*args, **kwargs)

    @classmethod
    def _get_manager_with_default_filtering(cls, manager, q_filter):
        """This is wrapping the manager class so we can add an extra
        filter to the queryset returned via get_queryset."""

        class ManagerWithFiltering(manager):
            def get_queryset(self):
                # Check the queryset caching django uses during these lookups -
                # we only want to add the q_filter the first time.
                from_cache = self.prefetch_cache_name in getattr(
                    self.instance, '_prefetched_objects_cache', {}
                )
                qs = super().get_queryset()
                if not from_cache and q_filter:
                    # Here is where we add the filter.
                    qs = qs.filter(q_filter)
                return qs

        return ManagerWithFiltering

    @cached_property
    def related_manager_cls(self):
        cls = super().related_manager_cls
        return self._get_manager_with_default_filtering(cls, self.q_filter)


class FilterableManyToManyField(models.fields.related.ManyToManyField):
    """This class builds on ManyToManyField to allow us to filter the relation
    to a subset, similar to how we use the unfiltered manager to filter out
    deleted instances of other foreign keys.

    It takes an additional Q object arg (q_filter) which will be applied to the
    queryset on *both* sides of the many-to-many relation.  Because it's
    applied to both sides the filter will typically be on the ManyToManyField
    itself.

    For example, class A and class B have a ManyToMany relation between them,
    via class M (so M would have a foreign key to both A and B).
    For an instance a of A, a.m would be:
    `B.objects.filter(a__in=a.id, q_filter)`,
    and for an instance b of B, b.m would be:
    `A.objects.filter(b__in=b.id, q_filter)`.
    If `q_filter` was `Q(m__deleted=False)` it would filter out all soft
    deleted instances of M.
    """

    def __init__(self, *args, **kwargs):
        self.q_filter = kwargs.pop('q_filter', None)
        super().__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name, **kwargs):
        """All we're doing here is overriding the `setattr` so it creates an
        instance of FilterableManyToManyDescriptor rather than
        ManyToManyDescriptor, and pass down the q_filter property."""
        super().contribute_to_class(cls, name, **kwargs)
        # Add the descriptor for the m2m relation.
        setattr(
            cls,
            self.name,
            FilterableManyToManyDescriptor(
                self.remote_field, reverse=False, q_filter=self.q_filter
            ),
        )

    def contribute_to_related_class(self, cls, related):
        """All we're doing here is overriding the `setattr` so it creates an
        instance of FilterableManyToManyDescriptor rather than
        ManyToManyDescriptor, and pass down the q_filter property."""
        super().contribute_to_related_class(cls, related)
        if (
            not self.remote_field.is_hidden()
            and not related.related_model._meta.swapped
        ):
            setattr(
                cls,
                related.get_accessor_name(),
                FilterableManyToManyDescriptor(
                    self.remote_field, reverse=True, q_filter=self.q_filter
                ),
            )


class GroupConcat(models.Aggregate):
    function = 'GROUP_CONCAT'
    allow_distinct = True


class Inet6Ntoa(Func):
    function = 'INET6_NTOA'
    output_field = CharField()
