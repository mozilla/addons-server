import os

from datetime import datetime

from django.db import models
from django.conf import settings

import amo.models


class BlogCacheRyf(models.Model):

    title = models.CharField(max_length=255, default='', blank=True)
    excerpt = models.TextField(blank=True)
    permalink = models.CharField(max_length=255, default='', blank=True)
    date_posted = models.DateTimeField(default=datetime.now, blank=True)
    image = models.CharField(max_length=255, default='', blank=True)

    class Meta:
        db_table = 'blog_cache_ryf'

    def get_image_url(self):
        return os.path.join(settings.STATIC_URL, 'ryf/', self.image.lstrip('/'))

    def __unicode__(self):
        return self.title


class DiscoveryModule(amo.models.ModelBase):
    """
    Keeps the application, ordering, and locale metadata for a module.

    The modules are defined statically in modules.py and linked to a database
    row through the module's name.
    """
    app = models.ForeignKey('applications.Application')
    module = models.CharField(max_length=255)
    ordering = models.IntegerField(null=True, blank=True)
    locales = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'discovery_modules'
