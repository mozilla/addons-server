import time

from django.conf import settings
from django.db import models

import amo.models
from addons.models import Addon, AddonCategory
from applications.models import Application
from users.models import UserProfile
from translations.fields import (TranslatedField, LinkifiedField,
                                 translations_with_fallback)


class Collection(amo.models.ModelBase):
    uuid = models.CharField(max_length=36, blank=True, unique=True)
    name = TranslatedField()
    nickname = models.CharField(max_length=30, blank=True, unique=True,
                                null=True)
    description = LinkifiedField()
    default_locale = models.CharField(max_length=10, default='en-US',
                                      db_column='defaultlocale')
    collection_type = models.PositiveIntegerField(default=0)
    icontype = models.CharField(max_length=25, blank=True)

    access = models.BooleanField(default=False)
    listed = models.BooleanField(
        default=True, help_text='Collections are either listed or private.')
    password = models.CharField(max_length=255, blank=True)

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
    users = models.ManyToManyField(UserProfile, through='CollectionUser')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collections'

    def get_url_path(self):
        # TODO(jbalogh): reverse
        return '/collection/%s' % self.url_slug

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.default_locale)

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

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


class CollectionAddon(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    collection = models.ForeignKey(Collection)
    added = models.DateTimeField()
    # category (deprecated: for "Fashion Your Firefox")
    comments = TranslatedField(null=True)
    downloads = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(UserProfile)

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
