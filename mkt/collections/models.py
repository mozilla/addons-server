from django.db import models
from django.db.models import Max

import amo.models
import mkt.regions
from addons.models import Category
from mkt.webapps.models import Webapp
from translations.fields import PurifiedField, save_signal

from .constants import COLLECTION_TYPES
from .managers import PublicCollectionsManager


class Collection(amo.models.ModelBase):
    collection_type = models.IntegerField(choices=COLLECTION_TYPES)
    description = PurifiedField()
    name = PurifiedField()
    is_public = models.BooleanField(default=False)
    # FIXME: add better / composite indexes that matches the query we are
    # going to make.
    category = models.ForeignKey(Category, null=True, blank=True)
    region = models.PositiveIntegerField(default=None, null=True, blank=True,
        choices=mkt.regions.REGIONS_CHOICES_ID, db_index=True)
    carrier = models.IntegerField(default=None, null=True, blank=True,
        choices=mkt.carriers.CARRIER_CHOICES, db_index=True)
    author = models.CharField(max_length=255, default='', blank=True)

    objects = amo.models.ManagerBase()
    public = PublicCollectionsManager()

    class Meta:
        db_table = 'app_collections'
        ordering = ('-id',)  # This will change soon since we'll need to be
                             # able to order collections themselves, but this
                             # helps tests for now.

    def __unicode__(self):
        return self.name.localized_string_clean

    def apps(self):
        """
        Return a list containing all apps in this collection.
        """
        return [a.app for a in self.collectionmembership_set.all()]

    def add_app(self, app, order=None):
        """
        Add an app to this collection. If specified, the app will be created
        with the specified `order`. If not, it will be added to the end of the
        collection.
        """
        if not order:
            qs = CollectionMembership.objects.filter(collection=self)
            aggregate = qs.aggregate(Max('order'))['order__max']
            order = aggregate + 1 if aggregate else 1
        return CollectionMembership.objects.create(collection=self, app=app,
                                                   order=order)

    def remove_app(self, app):
        """
        Remove the passed app from this collection, returning a boolean
        indicating whether a successful deletion took place.
        """
        try:
            membership = self.collectionmembership_set.get(app=app)
        except CollectionMembership.DoesNotExist:
            return False
        else:
            membership.delete()
            return True

    def reorder(self, new_order):
        """
        Passed a list of app IDs, e.g.

        [18, 24, 9]

        will change the order of each item in the collection to match the passed
        order. A ValueError will be raised if each app in the collection is not
        included in the ditionary.
        """
        if set(a.pk for a in self.apps()) != set(new_order):
            raise ValueError('Not all apps included')
        for order, pk in enumerate(new_order):
            CollectionMembership.objects.get(collection=self,
                                             app_id=pk).update(order=order)


class CollectionMembership(amo.models.ModelBase):
    collection = models.ForeignKey(Collection)
    app = models.ForeignKey(Webapp)
    order = models.SmallIntegerField(null=True)

    def __unicode__(self):
        return u'"%s" in "%s"' % (self.app.name,
                                  self.collection.name)

    class Meta:
        db_table = 'app_collection_membership'
        unique_together = ('collection', 'app',)
        ordering = ('order',)


models.signals.pre_save.connect(save_signal, sender=Collection,
                                dispatch_uid='collection_translations')
