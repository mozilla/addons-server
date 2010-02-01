from django.db import models

from caching.base import CachingMixin, CachingManager


class User(CachingMixin, models.Model):
    name = models.CharField(max_length=30)

    objects = CachingManager()


class Addon(CachingMixin, models.Model):
    val = models.IntegerField()
    author1 = models.ForeignKey(User)
    author2 = models.ForeignKey(User, related_name='author2_set')

    objects = CachingManager()
