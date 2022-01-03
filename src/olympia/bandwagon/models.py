import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse

from olympia import activity, amo
from olympia.addons.models import Addon
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ManagerBase, ModelBase
from olympia.translations.fields import (
    LinkifiedField,
    NoURLsField,
    TranslatedField,
    save_signal,
)
from olympia.users.models import UserProfile


class CollectionManager(ManagerBase):
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.transform(Collection.transformer)


class Collection(ModelBase):
    id = PositiveAutoField(primary_key=True)

    uuid = models.UUIDField(blank=True, unique=True, null=True)
    name = TranslatedField(require_locale=False)
    slug = models.CharField(max_length=30, blank=True, null=True)

    # description can (and sometimes does) contain html and other unsanitized
    # content. It must be cleaned before display - NoURLsField just strips the
    # URL without doing any escaping.
    description = NoURLsField(require_locale=False)
    default_locale = models.CharField(
        max_length=10, default='en-US', db_column='defaultlocale'
    )
    listed = models.BooleanField(
        default=True, help_text='Collections are either listed or private.'
    )

    addon_count = models.PositiveIntegerField(default=0, db_column='addonCount')

    addons = models.ManyToManyField(
        Addon, through='CollectionAddon', related_name='collections'
    )
    author = models.ForeignKey(
        UserProfile, null=True, related_name='collections', on_delete=models.CASCADE
    )

    objects = CollectionManager()

    class Meta(ModelBase.Meta):
        db_table = 'collections'
        indexes = [
            models.Index(fields=('created',), name='collections_created_idx'),
            models.Index(fields=('listed',), name='collections_listed_idx'),
            models.Index(fields=('slug',), name='collections_slug_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('author', 'slug'), name='author_id'),
        ]

    def __str__(self):
        return f'{self.name} ({self.addon_count})'

    def save(self, **kw):
        if not self.uuid:
            self.uuid = uuid.uuid4()
        if not self.slug:
            # Work with both, strings (if passed manually on .create()
            # and UUID instances)
            self.slug = str(self.uuid).replace('-', '')[:30]
        self.clean_slug()

        super().save(**kw)

    def clean_slug(self):
        if not self.author:
            return

        qs = self.author.collections.using('default')
        slugs = {slug: id for slug, id in qs.values_list('slug', 'id')}
        if self.slug in slugs and slugs[self.slug] != self.id:
            for idx in range(len(slugs)):
                new = f'{self.slug}-{idx + 1}'
                if new not in slugs:
                    self.slug = new
                    return

    def get_url_path(self):
        return reverse('collections.detail', args=[self.author_id, self.slug])

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    def add_addon(self, addon):
        CollectionAddon.objects.get_or_create(addon=addon, collection=self)

    def remove_addon(self, addon):
        CollectionAddon.objects.filter(addon=addon, collection=self).delete()

    def owned_by(self, user):
        return user.id == self.author_id

    def is_public(self):
        return self.listed

    @staticmethod
    def transformer(collections):
        if not collections:
            return
        author_ids = {c.author_id for c in collections}
        authors = {u.id: u for u in UserProfile.objects.filter(id__in=author_ids)}
        for c in collections:
            c.author = authors.get(c.author_id)

    @staticmethod
    def post_save(sender, instance, **kwargs):
        from . import tasks

        if kwargs.get('raw'):
            return
        tasks.collection_meta.delay(instance.id)


models.signals.post_save.connect(
    Collection.post_save, sender=Collection, dispatch_uid='coll.post_save'
)
models.signals.pre_save.connect(
    save_signal, sender=Collection, dispatch_uid='coll_translations'
)


class CollectionAddon(ModelBase):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    # category (deprecated: for "Fashion Your Firefox")
    comments = LinkifiedField(null=True)
    user = models.ForeignKey(UserProfile, null=True, on_delete=models.CASCADE)

    ordering = models.PositiveIntegerField(
        default=0,
        help_text='Add-ons are displayed in ascending order based on this field.',
    )

    class Meta(ModelBase.Meta):
        db_table = 'addons_collections'
        indexes = [
            models.Index(
                fields=('collection', 'created'), name='addons_collections_created_idx'
            ),
            models.Index(fields=('addon',), name='addons_collections_addon_idx'),
            models.Index(fields=('collection',), name='collection_id'),
            models.Index(fields=('user',), name='addons_collections_user_id'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('addon', 'collection'), name='addon_id_2'),
        ]

    @staticmethod
    def post_save(sender, instance, **kwargs):
        """Update Collection.addon_count and reindex add-on if the collection
        is featured."""
        from olympia.addons.tasks import index_addons

        if kwargs.get('raw'):
            return
        if instance.collection.listed:
            activity.log_create(
                amo.LOG.ADD_TO_COLLECTION, instance.addon, instance.collection
            )
        kwargs['addons'] = [instance.addon]
        Collection.post_save(sender, instance.collection, **kwargs)
        if instance.collection.id == settings.COLLECTION_FEATURED_THEMES_ID:
            # That collection is special: each add-on in it is considered
            # recommended, so we need to index the corresponding add-on.
            # (Note: we are considering the add-on in a given CollectionAddon
            #  never changes, to change add-ons belonging to a collection we
            #  add or remove CollectionAddon instances, we never modify the
            #  addon foreignkey of an existing instance).
            index_addons.delay([instance.addon.id])

    @staticmethod
    def post_delete(sender, instance, **kwargs):

        from olympia.addons.tasks import index_addons

        if kwargs.get('raw'):
            return
        if instance.collection.listed:
            activity.log_create(
                amo.LOG.REMOVE_FROM_COLLECTION, instance.addon, instance.collection
            )
        kwargs['addons'] = [instance.addon]
        Collection.post_save(sender, instance.collection, **kwargs)
        if instance.collection.id == settings.COLLECTION_FEATURED_THEMES_ID:
            # That collection is special: each add-on in it is considered
            # recommended, so we need to index the add-on we just removed from
            # it.
            index_addons.delay([instance.addon.id])


models.signals.pre_save.connect(
    save_signal, sender=CollectionAddon, dispatch_uid='coll_addon_translations'
)
# Update Collection.addon_count when a collectionaddon changes.
models.signals.post_save.connect(
    CollectionAddon.post_save, sender=CollectionAddon, dispatch_uid='coll.post_save'
)
models.signals.post_delete.connect(
    CollectionAddon.post_delete, sender=CollectionAddon, dispatch_uid='coll.post_delete'
)
