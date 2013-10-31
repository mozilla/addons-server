import collections
import hashlib
import os
import re
import time
import uuid
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.db import connection, models, transaction

import caching.base as caching

import amo
import amo.models
import sharing.utils as sharing
from access import acl
from addons.models import Addon, AddonRecommendation
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import sorted_groupby
from applications.models import Application
from stats.models import CollectionShareCountTotal
from translations.fields import LinkifiedField, save_signal, TranslatedField
from users.models import UserProfile
from versions import compare

SPECIAL_SLUGS = amo.COLLECTION_SPECIAL_SLUGS


class TopTags(object):
    """Descriptor to manage a collection's top tags in cache."""

    def key(self, obj):
        return '%s:top-tags:%s' % (settings.CACHE_PREFIX, obj.id)

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return cache.get(self.key(obj), [])

    def __set__(self, obj, value):
        two_days = 60 * 60 * 24 * 2
        cache.set(self.key(obj), value, two_days)


class CollectionManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(CollectionManager, self).get_query_set()
        return qs.transform(Collection.transformer)

    def manual(self):
        """Only hand-crafted, favorites, and featured collections should appear
        in this filter."""
        types = (amo.COLLECTION_NORMAL, amo.COLLECTION_FAVORITES,
                 amo.COLLECTION_FEATURED, )

        return self.filter(type__in=types)

    def listed(self):
        """Return public collections only."""
        return self.filter(listed=True)

    def publishable_by(self, user):
        """Collections that are publishable by a user."""
        owned_by = list(self.filter(author=user.id))
        publishable_by = list(self.filter(users=user.id))
        return set(owned_by + publishable_by)


class CollectionBase:
    """A mixin with methods common to Collection and SyncedCollection."""

    @classmethod
    def make_index(cls, addon_ids):
        ids = ':'.join(map(str, sorted(addon_ids)))
        return hashlib.md5(ids).hexdigest()

    def get_recs(self, app, version):
        addons = list(self.addons.values_list('id', flat=True))
        return self.get_recs_from_ids(addons, app, version)

    @classmethod
    def get_recs_from_ids(cls, addons, app, version, compat_mode='strict'):
        vint = compare.version_int(version)
        recs = RecommendedCollection.build_recs(addons)
        qs = (Addon.objects.public()
              .filter(id__in=recs, appsupport__app=app.id,
                      appsupport__min__lte=vint))
        if compat_mode == 'strict':
            qs = qs.filter(appsupport__max__gte=vint)
        return recs, qs


class Collection(CollectionBase, amo.models.ModelBase):

    TYPE_CHOICES = amo.COLLECTION_CHOICES.items()

    uuid = models.CharField(max_length=36, blank=True, unique=True)
    name = TranslatedField(require_locale=False)
    # nickname is deprecated.  Use slug.
    nickname = models.CharField(max_length=30, blank=True, unique=True,
                                null=True)
    slug = models.CharField(max_length=30, blank=True, null=True)

    description = LinkifiedField(require_locale=False)
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
    all_personas = models.BooleanField(default=False,
        help_text='Does this collection only contain Themes?')

    addons = models.ManyToManyField(Addon, through='CollectionAddon',
                                    related_name='collections')
    author = models.ForeignKey(UserProfile, null=True,
                               related_name='collections')
    users = models.ManyToManyField(UserProfile, through='CollectionUser',
                                  related_name='collections_publishable')

    addon_index = models.CharField(max_length=40, null=True, db_index=True,
        help_text='Custom index for the add-ons in this collection')

    # This gets overwritten in the transformer.
    share_counts = collections.defaultdict(int)

    objects = CollectionManager()

    top_tags = TopTags()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collections'
        unique_together = (('author', 'slug'),)

    def __unicode__(self):
        return u'%s (%s)' % (self.name, self.addon_count)

    def flush_urls(self):
        urls = ['*%s' % self.get_url_path(),
                self.icon_url]
        return urls

    def save(self, **kw):
        if not self.uuid:
            self.uuid = unicode(uuid.uuid4())
        if not self.slug:
            self.slug = self.uuid[:30]
        self.clean_slug()

        # Maintain our index of add-on ids.
        if self.id:
            ids = self.addons.values_list('id', flat=True)
            self.addon_index = self.make_index(ids)

        super(Collection, self).save(**kw)

    def clean_slug(self):
        if self.type in SPECIAL_SLUGS:
            self.slug = SPECIAL_SLUGS[self.type]
            return

        if self.slug in SPECIAL_SLUGS.values():
            self.slug += '~'

        if not self.author:
            return

        qs = self.author.collections.using('default')
        slugs = dict((slug, id) for slug, id in qs.values_list('slug', 'id'))
        if self.slug in slugs and slugs[self.slug] != self.id:
            for idx in range(len(slugs)):
                new = '%s-%s' % (self.slug, idx + 1)
                if new not in slugs:
                    self.slug = new
                    return

    def get_url_path(self):
        return reverse('collections.detail',
                        args=[self.author_username, self.slug])

    def get_abs_url(self):
        return absolutify(self.get_url_path())

    def get_img_dir(self):
        return os.path.join(settings.COLLECTIONS_ICON_PATH,
                            str(self.id / 1000))

    def upvote_url(self):
        return reverse('collections.vote',
                       args=[self.author_username, self.slug, 'up'])

    def downvote_url(self):
        return reverse('collections.vote',
                       args=[self.author_username, self.slug, 'down'])

    def edit_url(self):
        return reverse('collections.edit',
                       args=[self.author_username, self.slug])

    def watch_url(self):
        return reverse('collections.watch',
                        args=[self.author_username, self.slug])

    def delete_url(self):
        return reverse('collections.delete',
                       args=[self.author_username, self.slug])

    def delete_icon_url(self):
        return reverse('collections.delete_icon',
                       args=[self.author_username, self.slug])

    def share_url(self):
        return reverse('collections.share',
                       args=[self.author_username, self.slug])

    def feed_url(self):
        return reverse('collections.detail.rss',
                       args=[self.author_username, self.slug])

    def stats_url(self):
        return reverse('collections.stats',
                       args=[self.author_username, self.slug])

    @property
    def author_username(self):
        return self.author.username if self.author else 'anonymous'

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
            # [1] is the whole ID, [2] is the directory
            split_id = re.match(r'((\d*?)\d{1,3})$', str(self.id))
            return settings.COLLECTION_ICON_URL % (
                    split_id.group(2) or 0, self.id, modified)
        elif self.type == amo.COLLECTION_FAVORITES:
            return settings.MEDIA_URL + 'img/icons/heart.png'
        else:
            return settings.MEDIA_URL + 'img/icons/collection.png'

    def set_addons(self, addon_ids, comments={}):
        """Replace the current add-ons with a new list of add-on ids."""
        order = dict((a, idx) for idx, a in enumerate(addon_ids))

        # Partition addon_ids into add/update/remove buckets.
        existing = set(self.addons.using('default')
                       .values_list('id', flat=True))
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
            if self.listed:
                for addon in remove:
                    amo.log(amo.LOG.REMOVE_FROM_COLLECTION,
                            (Addon, addon), self)
        if add:
            insert = '(%s, %s, %s, NOW(), NOW(), 0)'
            values = [insert % (a, self.id, idx) for a, idx in add]
            cursor.execute("""
                INSERT INTO addons_collections
                    (addon_id, collection_id, ordering, created,
                     modified, downloads)
                VALUES %s""" % ','.join(values))
            if self.listed:
                for addon_id, idx in add:
                    amo.log(amo.LOG.ADD_TO_COLLECTION,
                            (Addon, addon_id), self)
        for addon, ordering in update:
            (CollectionAddon.objects.filter(collection=self.id, addon=addon)
             .update(ordering=ordering, modified=now))

        for addon, comment in comments.iteritems():
            c = (CollectionAddon.objects.using('default')
                 .filter(collection=self.id, addon=addon))
            if c.exists():
                c[0].comments = comment
                c[0].save(force_update=True)

        self.save()

    def is_subscribed(self, user):
        """Determines if the user is subscribed to this collection."""
        return self.following.filter(user=user).exists()

    def add_addon(self, addon):
        "Adds an addon to the collection."
        CollectionAddon.objects.get_or_create(addon=addon, collection=self)
        if self.listed:
            amo.log(amo.LOG.ADD_TO_COLLECTION, addon, self)
        self.save()  # To invalidate Collection.

    def remove_addon(self, addon):
        CollectionAddon.objects.filter(addon=addon, collection=self).delete()
        if self.listed:
            amo.log(amo.LOG.REMOVE_FROM_COLLECTION, addon, self)
        self.save()  # To invalidate Collection.

    def owned_by(self, user):
        return (user.id == self.author_id)

    def can_view_stats(self, request):
        if request and request.amo_user:
            return (self.publishable_by(request.amo_user) or
                    acl.action_allowed(request, 'CollectionStats', 'View'))
        return False

    @caching.cached_method
    def publishable_by(self, user):
        return bool(self.owned_by(user) or self.users.filter(pk=user.id))

    @staticmethod
    def transformer(collections):
        if not collections:
            return
        author_ids = set(c.author_id for c in collections)
        authors = dict((u.id, u) for u in
                       UserProfile.objects.filter(id__in=author_ids))
        for c in collections:
            c.author = authors.get(c.author_id)
        c_dict = dict((c.pk, c) for c in collections)
        sharing.attach_share_counts(CollectionShareCountTotal, 'collection',
                                    c_dict)

    @staticmethod
    def post_save(sender, instance, **kwargs):
        from . import tasks
        if kwargs.get('raw'):
            return
        tasks.collection_meta.delay(instance.id, using='default')
        tasks.index_collections.delay([instance.id])

    @staticmethod
    def post_delete(sender, instance, **kwargs):
        from . import tasks
        if kwargs.get('raw'):
            return
        tasks.unindex_collections.delay([instance.id])

    def check_ownership(self, request, require_owner, require_author,
                        ignore_disabled, admin):
        """
        Used by acl.check_ownership to see if request.user has permissions for
        the collection.
        """
        from access import acl
        return acl.check_collection_ownership(request, self, require_owner)


models.signals.post_save.connect(Collection.post_save, sender=Collection,
                                 dispatch_uid='coll.post_save')
models.signals.pre_save.connect(save_signal, sender=Collection,
                                dispatch_uid='coll_translations')
models.signals.post_delete.connect(Collection.post_delete, sender=Collection,
                                   dispatch_uid='coll.post_delete')


class CollectionAddon(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    collection = models.ForeignKey(Collection)
    # category (deprecated: for "Fashion Your Firefox")
    comments = LinkifiedField(null=True)
    downloads = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(UserProfile, null=True)

    ordering = models.PositiveIntegerField(default=0,
        help_text='Add-ons are displayed in ascending order '
                  'based on this field.')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'addons_collections'
        unique_together = (('addon', 'collection'),)


models.signals.pre_save.connect(save_signal, sender=CollectionAddon,
                                dispatch_uid='coll_addon_translations')


class CollectionFeature(amo.models.ModelBase):
    title = TranslatedField()
    tagline = TranslatedField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_features'

models.signals.pre_save.connect(save_signal, sender=CollectionFeature,
                                dispatch_uid='collectionfeature_translations')


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


class CollectionWatcher(amo.models.ModelBase):
    collection = models.ForeignKey(Collection, related_name='following')
    user = models.ForeignKey(UserProfile)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'collection_subscriptions'

    def flush_urls(self):
        urls = ['*/user/%d/' % self.user_id]
        return urls

    @staticmethod
    def post_save_or_delete(sender, instance, **kw):
        from . import tasks
        tasks.collection_watchers(instance.collection_id, using='default')


models.signals.post_save.connect(CollectionWatcher.post_save_or_delete,
                                 sender=CollectionWatcher)
models.signals.post_delete.connect(CollectionWatcher.post_save_or_delete,
                                   sender=CollectionWatcher)


class CollectionUser(models.Model):
    collection = models.ForeignKey(Collection)
    user = models.ForeignKey(UserProfile)
    role = models.SmallIntegerField(default=1,
            choices=amo.COLLECTION_AUTHOR_CHOICES.items())

    class Meta:
        db_table = 'collections_users'


class CollectionVote(models.Model):
    collection = models.ForeignKey(Collection, related_name='votes')
    user = models.ForeignKey(UserProfile, related_name='votes')
    vote = models.SmallIntegerField(default=0)
    created = models.DateTimeField(null=True, auto_now_add=True)

    class Meta:
        db_table = 'collections_votes'

    def flush_urls(self):
        urls = ['*%s' % self.collection.get_url_path()]
        return urls

    @staticmethod
    def post_save_or_delete(sender, instance, **kwargs):
        # There are some issues with cascade deletes, where the
        # collection disappears before the votes. Make sure the
        # collection exists before trying to update it in the task.
        if Collection.objects.filter(id=instance.collection_id).exists():
            from . import tasks
            tasks.collection_votes(instance.collection_id, using='default')


models.signals.post_save.connect(CollectionVote.post_save_or_delete,
                                 sender=CollectionVote)
models.signals.post_delete.connect(CollectionVote.post_save_or_delete,
                                   sender=CollectionVote)


class SyncedCollection(CollectionBase, amo.models.ModelBase):
    """
    We remember what add-ons a user has installed with this table.

    The addon guids come in from the discovery pane and we translate those to
    addon ids. If those addons match an addon_index of an existing
    SyncedCollection its count is incremented; otherwise a new collection is
    created for that bag of addons.

    This uses separate tables because we don't want the high volume of data to
    crush performance on normal collection tables. SyncedCollections are used
    to generate recommendations and may be used for other data mining in the
    future.
    """
    addon_index = models.CharField(max_length=40, null=True,
                                   db_index=True, unique=True,
        help_text='md5 of addon ids in this collection for fast comparisons')
    addons = models.ManyToManyField(Addon, through='SyncedCollectionAddon',
                                    related_name='synced_collections')
    count = models.IntegerField("Number of users with this collection.",
                                default=0)

    class Meta:
        db_table = 'synced_collections'

    def save(self, **kw):
        return super(SyncedCollection, self).save(**kw)

    def set_addons(self, addon_ids):
        # SyncedCollections are only written once so we don't need to deal with
        # updates or deletes.
        cursor = connection.cursor()
        values = ['(%s,%s)' % (addon, self.id) for addon in addon_ids]
        cursor.execute("""
            INSERT INTO synced_addons_collections (addon_id, collection_id)
            VALUES %s""" % ','.join(values))
        if not self.addon_index:
            self.addon_index = self.make_index(addon_ids)
            self.save()
        transaction.commit_unless_managed()


class SyncedCollectionAddon(models.Model):
    addon = models.ForeignKey(Addon)
    collection = models.ForeignKey(SyncedCollection)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'synced_addons_collections'
        unique_together = (('addon', 'collection'),)


class RecommendedCollection(Collection):

    class Meta:
        proxy = True

    def save(self, **kw):
        self.type = amo.COLLECTION_RECOMMENDED
        return super(RecommendedCollection, self).save(**kw)

    @classmethod
    def build_recs(cls, addon_ids):
        """Get the top ranking add-ons according to recommendation scores."""
        scores = AddonRecommendation.scores(addon_ids)
        d = collections.defaultdict(int)
        for others in scores.values():
            for addon, score in others.items():
                d[addon] += score
        addons = sorted(d.items(), key=lambda x: x[1], reverse=True)
        return [addon for addon, score in addons if addon not in addon_ids]


class FeaturedCollection(amo.models.ModelBase):
    application = models.ForeignKey(Application)
    collection = models.ForeignKey(Collection)
    locale = models.CharField(max_length=10, null=True)

    class Meta:
        db_table = 'featured_collections'

    def __unicode__(self):
        return u'%s (%s: %s)' % (self.collection, self.application,
                                 self.locale)


class MonthlyPick(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    blurb = models.TextField()
    image = models.URLField()
    locale = models.CharField(max_length=10, unique=True, null=True,
                              blank=True)

    class Meta:
        db_table = 'monthly_pick'
