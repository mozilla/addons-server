from datetime import datetime
from django.db import models


class BlogCacheRyf(models.Model):

    title = models.CharField(max_length=255, default='', blank=True)
    excerpt = models.TextField(blank=True)
    permalink = models.CharField(max_length=255, default='', blank=True)
    date_posted = models.DateTimeField(default=datetime.now, blank=True)
    image = models.CharField(max_length=255, default='', blank=True)

    class Meta:
        db_table = 'blog_cache_ryf'

    def __unicode__(self):
        return self.title
