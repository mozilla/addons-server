from django.db import models

import amo.models


class Tag(amo.models.ModelBase):
    tag_text = models.CharField(max_length=128)
    blacklisted = models.BooleanField(default=False)
    addons = models.ManyToManyField('addons.Addon', through='AddonTag',
                                    related_name='tags')

    class Meta:
        db_table = 'tags'
        ordering = ('tag_text',)

    def __unicode__(self):
        return self.tag_text

    @property
    def popularity(self):
        return self.tagstat.num_addons


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
