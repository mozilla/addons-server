from datetime import datetime

from django.db import models

import caching


class Approval(caching.CachingMixin, models.Model):

    created = models.DateTimeField(default=datetime.now)
    reviewtype = models.CharField(max_length=10, default='pending')
    action = models.IntegerField(default=0)
    os = models.CharField(max_length=255, default='')
    applications = models.CharField(max_length=255, default='')
    comments = models.TextField(null=True)

    addon = models.ForeignKey('addons.Addon')
    user = models.ForeignKey('users.User')
    #file = models.ForeignKey('files.File')
    reply_to = models.ForeignKey('self', null=True, db_column='reply_to')

    objects = caching.CachingManager()

    class Meta:
        db_table = 'approvals'
        get_latest_by = 'created'
