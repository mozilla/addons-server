from datetime import datetime

from django.db import models

import amo
from translations.fields import TranslatedField


class HubPromo(amo.ModelBase):
    VISIBILITY_CHOICES = (
        (0, 'Nobody'),
        (1, 'Visitors'),
        (2, 'Developers'),
        (3, 'Visitors and Developers'),
    )

    heading = TranslatedField()
    body = TranslatedField()
    visibility = models.SmallIntegerField(choices=VISIBILITY_CHOICES)

    class Meta:
        db_table = 'hubpromos'

    def __unicode__(self):
        return unicode(self.heading)


class HubEvent(amo.ModelBase):
    name = models.CharField(max_length=255, default='')
    url = models.URLField(max_length=255, default='')
    location = models.CharField(max_length=255, default='')
    date = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubevents'

    def __unicode__(self):
        return self.name
