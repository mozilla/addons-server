from django.db import models

import amo.models
from amo.urlresolvers import reverse


class TagManager(amo.models.ManagerBase):

    def not_blacklisted(self):
        """Get allowed tags only"""
        return self.filter(blacklisted=False)


class Tag(amo.models.ModelBase):
    tag_text = models.CharField(max_length=128)
    blacklisted = models.BooleanField(default=False)
    addons = models.ManyToManyField('addons.Addon', through='AddonTag',
                                    related_name='tags')

    objects = TagManager()

    class Meta:
        db_table = 'tags'
        ordering = ('tag_text',)

    def __unicode__(self):
        return self.tag_text

    @property
    def popularity(self):
        return self.tagstat.num_addons

    def get_url_path(self):
        return reverse('tags.detail', args=[self.tag_text])

    def flush_urls(self):
        urls = ['*/tag/%s' % self.tag_text, ]

        return urls


class TagStat(amo.models.ModelBase):
    tag = models.OneToOneField(Tag, primary_key=True)
    num_addons = models.IntegerField()

    class Meta:
        db_table = 'tag_stat'


class AddonTag(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='addon_tags')
    tag = models.ForeignKey(Tag, related_name='addon_tags')
    user = models.ForeignKey('users.UserProfile')

    class Meta:
        db_table = 'users_tags_addons'

    def flush_urls(self):
        urls = ['*/addon/%d/' % self.addon_id,
                '*/tag/%s' % self.tag.tag_text, ]

        return urls
