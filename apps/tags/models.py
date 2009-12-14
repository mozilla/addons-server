from django.db import models

import amo


class Tag(amo.ModelBase):
    tag_text = models.CharField(max_length=128)
    blacklisted = models.BooleanField(default=False)
    addons = models.ManyToManyField('addons.Addon', through='AddonTag')

    class Meta:
        db_table = 'tags'

    @property
    def popularity(self):
        return self.tagstat.num_addons


class TagStat(amo.ModelBase):
    tag = models.OneToOneField(Tag, primary_key=True)
    num_addons = models.IntegerField()

    class Meta:
        db_table = 'tag_stat'


class AddonTag(amo.ModelBase):
    addon = models.ForeignKey('addons.Addon')
    tag = models.ForeignKey(Tag)
    user = models.ForeignKey('users.UserProfile')

    class Meta:
        db_table = 'users_tags_addons'
