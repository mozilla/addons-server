from django.urls import NoReverseMatch
from django.db import models

from olympia import activity, amo
from olympia.amo.models import ManagerBase, ModelBase
from olympia.amo.urlresolvers import reverse


class TagManager(ManagerBase):
    def not_denied(self):
        """Get allowed tags only"""
        return self.filter(denied=False)


class Tag(ModelBase):
    tag_text = models.CharField(max_length=128)
    denied = models.BooleanField(default=False)
    restricted = models.BooleanField(default=False)
    addons = models.ManyToManyField(
        'addons.Addon', through='AddonTag', related_name='tags'
    )
    num_addons = models.IntegerField(default=0)

    objects = TagManager()

    class Meta:
        db_table = 'tags'
        ordering = ('tag_text',)

    def __unicode__(self):
        return self.tag_text

    @property
    def popularity(self):
        return self.num_addons

    def can_reverse(self):
        try:
            self.get_url_path()
            return True
        except NoReverseMatch:
            return False

    def get_url_path(self):
        return reverse('tags.detail', args=[self.tag_text])

    def save_tag(self, addon):
        tag, created = Tag.objects.get_or_create(tag_text=self.tag_text)
        AddonTag.objects.get_or_create(addon=addon, tag=tag)
        activity.log_create(amo.LOG.ADD_TAG, tag, addon)
        return tag

    def remove_tag(self, addon):
        tag, created = Tag.objects.get_or_create(tag_text=self.tag_text)
        for addon_tag in AddonTag.objects.filter(addon=addon, tag=tag):
            addon_tag.delete()
        activity.log_create(amo.LOG.REMOVE_TAG, tag, addon)

    def update_stat(self):
        if self.denied:
            return
        self.num_addons = self.addons.count()
        self.save()


class AddonTag(ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='addon_tags')
    tag = models.ForeignKey(Tag, related_name='addon_tags')

    class Meta:
        db_table = 'users_tags_addons'


def update_tag_stat_signal(sender, instance, **kw):
    from .tasks import update_tag_stat

    if not kw.get('raw'):
        try:
            update_tag_stat.delay(instance.tag.pk)
        except Tag.DoesNotExist:
            pass


models.signals.post_save.connect(
    update_tag_stat_signal, sender=AddonTag, dispatch_uid='update_tag_stat'
)
models.signals.post_delete.connect(
    update_tag_stat_signal, sender=AddonTag, dispatch_uid='delete_tag_stat'
)
