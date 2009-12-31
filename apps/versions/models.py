from django.db import models

import amo
from addons.models import Addon
from translations.fields import TranslatedField


class Version(amo.ModelBase):

    addon = models.ForeignKey(Addon)
    license = models.ForeignKey('License')

    releasenotes = TranslatedField()

    approvalnotes = models.TextField()
    version = models.CharField(max_length=255, default=0)

    class Meta(amo.ModelBase.Meta):
        db_table = 'versions'


class License(amo.ModelBase):

    rating = models.SmallIntegerField(default=-1)
    text = TranslatedField()

    class Meta(amo.ModelBase.Meta):
        db_table = 'licenses'
