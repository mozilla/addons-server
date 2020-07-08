from django.db import models

from olympia.amo import models as amo_models


class Artist(models.Model):
    name = models.CharField(max_length=50)


class Song(models.Model):
    name = models.CharField(max_length=50)
    performers = amo_models.FilterableManyToManyField(
        Artist,
        through='Singer',
        related_name='songs',
        q_filter=models.Q(singer__credited=True),
    )


class Singer(models.Model):
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE)
    credited = models.BooleanField(default=True)
