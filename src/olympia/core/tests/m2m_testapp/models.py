from django.db import models

from olympia.amo import models as amo_models
from olympia.amo.models import ModelBase


class Artist(ModelBase):
    name = models.CharField(max_length=50)


class Song(ModelBase):
    name = models.CharField(max_length=50)
    performers = amo_models.FilterableManyToManyField(
        Artist,
        through='Singer',
        related_name='songs',
        q_filter=models.Q(singer__credited=True),
    )


class Singer(ModelBase):
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE)
    credited = models.BooleanField(default=True)
