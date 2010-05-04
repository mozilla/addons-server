from datetime import datetime
import hashlib
import time
import uuid

from django.conf import settings
from django.db import models, connection

import amo
import amo.models
from amo.utils import sorted_groupby
from addons.models import Addon, AddonCategory
from applications.models import Application
from users.models import UserProfile
from translations.fields import TranslatedField, LinkifiedField


class CollectionManager(amo.models.ManagerBase):

    def listed(self):
        """Return public collections only."""
        return self.filter(listed=True)


class Collection(amo.models.ModelBase):

    TYPE_CHOICES = amo.COLLECTION_CHOICES.items()

    uuid = models.CharField(max_length=36, blank=True, unique=True)
    name = TranslatedField()
    nickname = models.CharField(max_length=30, blank=True, unique=True,
                                null=True)
    description = LinkifiedField()
    default_locale = models.CharField(max_length=10, default='en-US',
                                      db_column='defaultlocale')
    type = models.PositiveIntegerField(db_column='collection_type',
            choices=TYPE_CHOICES, default=0)
    icontype = models.CharField(max_length=25, blank=True)

    listed = models.BooleanField(
        default=True, help_text='Collections are either listed or private.')

    subscribers = models.PositiveIntegerField(default=0)
    downloads = models.PositiveIntegerField(default=0)
    weekly_subscribers = models.PositiveIntegerField(default=0)
    monthly_subscribers = models.PositiveIntegerField(default=0)
    application = models.ForeignKey(Application, null=True)
    addon_count = models.PositiveIntegerField(default=0,
                                              db_column='addonCount')

    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    rating = models.FloatField(default=0)

    addons = models.ManyToManyField(Addon, through='CollectionAddon',
                                    related_name='collections')
    users = models.ManyToManyField(UserProfile, through='CollectionUser',
                                  related_name='collections')

    addon_index = models.CharField(max_length=40, null=True, db_index=True,
        help_text='Custom index for the add-ons in this collection')
    recommended_collection = models.ForeignKey('self', null=True)

    objects = CollectionManager()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collections'

    def __unicode__(self):
        return u'%s (%s)' % (self.name, self.addon_count)

    def save(self, **kw):
        if not self.uuid:
            self.uuid = unicode(uuid.uuid4())

        # Maintain our index of add-on ids.
        if self.id:
            ids = self.addons.values_list('id', flat=True)
            self.addon_index = self.make_index(ids)

        super(Collection, self).save(**kw)

    def get_url_path(self):
        # TODO(jbalogh): reverse
        return '/collection/%s' % self.url_slug

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    @classmethod
    def make_index(cls, addon_ids):
        ids = ':'.join(map(str, sorted(addon_ids)))
        return hashlib.md5(ids).hexdigest()

    @property
    def url_slug(self):
        """uuid or nickname if chosen"""
        return self.nickname or self.uuid

    @property
    def icon_url(self):
        modified = int(time.mktime(self.modified.timetuple()))
        if self.icontype:
            return settings.COLLECTION_ICON_URL % (self.id, modified)
        else:
            return settings.MEDIA_URL + 'img/amo2009/icons/collection.png'

    def set_addons(self, addon_ids):
        """Replace the current add-ons with a new list of add-on ids."""
        order = dict((a, idx) for idx, a in enumerate(addon_ids))

        # Partition addon_ids into add/update/remove buckets.
        existing = set(self.addons.values_list('id', flat=True))
        add, update = [], []
        for addon in addon_ids:
            bucket = update if addon in existing else add
            bucket.append((addon, order[addon]))
        remove = existing.difference(addon_ids)

        cursor = connection.cursor()
        now = datetime.now()
        if remove:
            cursor.execute("DELETE FROM addons_collections "
                           "WHERE collection_id=%s AND addon_id IN (%s)" %
                           (self.id, ','.join(map(str, remove))))
        if add:
            insert = '(%s, %s, %s, NOW(), NOW(), NOW(), 0)'
            values = [insert % (a, self.id, idx) for a, idx in add]
            cursor.execute("""
                INSERT INTO addons_collections
                    (addon_id, collection_id, ordering, added, created,
                     modified, downloads)
                VALUES %s""" % ','.join(values))
        for addon, ordering in update:
            (CollectionAddon.objects.filter(collection=self.id, addon=addon)
             .update(ordering=ordering, modified=now))
        self.save()


class CollectionAddon(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    collection = models.ForeignKey(Collection)
    added = models.DateTimeField(auto_now_add=True)
    # category (deprecated: for "Fashion Your Firefox")
    comments = TranslatedField(null=True)
    downloads = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(UserProfile, null=True)

    ordering = models.PositiveIntegerField(default=0,
        help_text='Add-ons are displayed in ascending order '
                  'based on this field.')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'addons_collections'
        unique_together = (('addon', 'collection'),)


class CollectionAddonRecommendation(models.Model):
    collection = models.ForeignKey(Collection, null=True)
    addon = models.ForeignKey(Addon, null=True)
    score = models.FloatField(blank=True)

    class Meta:
        db_table = 'collection_addon_recommendations'


class CollectionCategory(amo.models.ModelBase):
    collection = models.ForeignKey(Collection)
    category = models.ForeignKey(AddonCategory)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_categories'


class CollectionFeature(amo.models.ModelBase):
    title = TranslatedField()
    tagline = TranslatedField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_features'


class CollectionPromo(amo.models.ModelBase):
    collection = models.ForeignKey(Collection, null=True)
    locale = models.CharField(max_length=10, null=True)
    collection_feature = models.ForeignKey(CollectionFeature)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_promos'
        unique_together = ('collection', 'locale', 'collection_feature')

    @staticmethod
    def transformer(promos):
        if not promos:
            return

        promo_dict = dict((p.id, p) for p in promos)
        q = (Collection.objects.no_cache()
             .filter(collectionpromo__in=promos)
             .extra(select={'promo_id': 'collection_promos.id'}))

        for promo_id, collection in (sorted_groupby(q, 'promo_id')):
            promo_dict[promo_id].collection = collection.next()


class CollectionRecommendation(amo.models.ModelBase):
    collection = models.ForeignKey(Collection, null=True,
            related_name="collection_one")
    other_collection = models.ForeignKey(Collection, null=True,
            related_name="collection_two")
    score = models.FloatField(blank=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_recommendations'


class CollectionSummary(models.Model):
    """This materialized view maintains a indexed summary of the text data
    in a collection to make search faster.

    `id` commented out due to django complaining because id is not actually a
    primary key here.  This is a candidate for deletion once remora is gone;
    bug 540638.  As soon as this info is in sphinx, this is method is
    deprecated.
    """
    #id = models.PositiveIntegerField()
    locale = models.CharField(max_length=10, blank=True)
    name = models.TextField()
    description = models.TextField()

    class Meta:
        db_table = 'collection_search_summary'


class CollectionSubscription(amo.models.ModelBase):
    collection = models.ForeignKey(Collection)
    user = models.ForeignKey(UserProfile)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_subscriptions'


class CollectionUser(models.Model):
    collection = models.ForeignKey(Collection)
    user = models.ForeignKey(UserProfile)
    role = models.SmallIntegerField(default=1,
            choices=amo.COLLECTION_AUTHOR_CHOICES.items())

    class Meta:
        db_table = 'collections_users'


class CollectionVote(models.Model):
    collection = models.ForeignKey(Collection)
    user = models.ForeignKey(UserProfile)
    vote = models.SmallIntegerField(default=0)
    created = models.DateTimeField(null=True)

    class Meta:
        db_table = 'collections_votes'


class SyncedCollection(Collection):
    """Collection that automatically sets type=SYNC."""

    class Meta:
        proxy = True

    def save(self, **kw):
        self.type = amo.COLLECTION_SYNCHRONIZED
        return super(SyncedCollection, self).save(**kw)
