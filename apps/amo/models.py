from django.db import models

import queryset_transform

import caching.base
from translations.fields import TranslatedFieldMixin
from translations import transformer

from .signals import register_signals


# Register Django signals this app listens to.
register_signals()


class TransformQuerySet(queryset_transform.TransformQuerySet):

    def pop_transforms(self):
        qs = self._clone()
        transforms = qs._transform_fns
        qs._transform_fns = []
        return transforms, qs

    def no_transforms(self):
        return self.pop_transforms()[1]


# Make TransformQuerySet one of CachingQuerySet's parents so that we can do
# transforms on objects and then get them cached.
CachingQuerySet = caching.base.CachingQuerySet
CachingQuerySet.__bases__ = (TransformQuerySet,) + CachingQuerySet.__bases__


class ManagerBase(caching.base.CachingManager):
    """
    Base for all managers in AMO.

    Returns TransformQuerySets from the queryset_transform project.

    If a model has translated fields, they'll be attached through a transform
    function.
    """

    def get_query_set(self):
        qs = super(ManagerBase, self).get_query_set()
        if hasattr(self.model._meta, 'translated_fields'):
            qs = qs.transform(transformer.get_trans)
        return qs

    def transform(self, fn):
        return self.all().transform(fn)


class ModelBase(caching.base.CachingMixin, models.Model):
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
