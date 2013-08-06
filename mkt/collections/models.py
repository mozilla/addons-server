from django.core.urlresolvers import reverse
from django.db import models
from django.db.models import Max

import amo.models
from mkt.webapps.models import Webapp
from translations.fields import PurifiedField, save_signal

from .constants import COLLECTION_TYPES


class Collection(amo.models.ModelBase):
    collection_type = models.IntegerField(choices=COLLECTION_TYPES, null=True)
    description = PurifiedField()
    name = PurifiedField()

    class Meta:
        db_table = 'app_collections'

    def __unicode__(self):
        return self.name.localized_string_clean

    def apps(self):
        """
        Return a list containing all apps in this collection.
        """
        return [a.app for a in self.collectionmembership_set.all()]

    def app_urls(self):
        """
        Returns a list of URLs of all apps in this collection.
        """
        return [reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': a.pk
        }) for a in self.apps()]

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
