import uuid

from datetime import datetime

from django.db import models

import olympia.core.logger

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.users.models import UserProfile


class RssKey(models.Model):
    # TODO: Convert to `models.UUIDField` but apparently we have a max_length
    # of 36 defined in the database and maybe store things with a hyphen
    # or maybe not...
    key = models.CharField(
        db_column='rsskey', max_length=36,
        default=lambda: uuid.uuid4().hex, unique=True)
    addon = models.ForeignKey(Addon, null=True, unique=True)
    user = models.ForeignKey(UserProfile, null=True, unique=True)
    created = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubrsskeys'


class BlogPost(ModelBase):
    title = models.CharField(max_length=255)
    date_posted = models.DateField(default=datetime.now)
    permalink = models.CharField(max_length=255)

    class Meta:
        db_table = 'blogposts'
