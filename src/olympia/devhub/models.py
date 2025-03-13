import uuid
from datetime import datetime

from django.db import models

import olympia.core.logger
from olympia.addons.models import Addon
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ModelBase
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('devhub')


class RssKey(models.Model):
    id = PositiveAutoField(primary_key=True)
    key = models.UUIDField(
        db_column='rsskey', unique=True, null=True, default=uuid.uuid4
    )
    addon = models.ForeignKey(Addon, null=True, unique=True, on_delete=models.CASCADE)
    user = models.ForeignKey(
        UserProfile, null=True, unique=True, on_delete=models.CASCADE
    )
    created = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubrsskeys'


class BlogPost(ModelBase):
    id = PositiveAutoField(primary_key=True)
    post_id = models.IntegerField(null=True)
    title = models.CharField(max_length=255)
    date_posted = models.DateField(default=datetime.now)
    date_modified = models.DateTimeField(default=datetime.now)
    permalink = models.CharField(max_length=255)

    class Meta:
        db_table = 'blogposts'
        ordering = ('-date_posted',)


class SurveyResponse(ModelBase):
    id = PositiveAutoField(primary_key=True)
    survey_id = models.IntegerField(help_text='Alchemer survey identifier.')
    user = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name='surveyresponse'
    )
    date_responded = models.DateTimeField(default=datetime.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['survey_id', 'user'], name='unique_survey_user'
            )
        ]
