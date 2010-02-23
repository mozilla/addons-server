from django.db import models

import amo.models
from addons.models import Addon, AddonCategory
from applications.models import Application
from users.models import UserProfile
from translations.fields import TranslatedField, LinkifiedField


class Collection(amo.models.ModelBase):
    uuid = models.CharField(max_length=36, blank=True, unique=True)
    name = TranslatedField()
    nickname = models.CharField(max_length=30, blank=True, unique=True)
    description = LinkifiedField()
    defaultlocale = models.CharField(max_length=10, default='en-US')
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
    addonCount = models.PositiveIntegerField(default=0)

    upvotes = models.PositiveIntegerField(default=0)
    downvotes = models.PositiveIntegerField(default=0)
    rating = models.FloatField(default=0)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collections'

    def get_absolute_url(self):
        return '/collection/%s' % self.url_slug

    @property
    def url_slug(self):
        """uuid or nickname if chosen"""
        return self.nickname or self.uuid


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
