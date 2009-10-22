from django.db import models

import amo
from users.models import User


class Review(amo.LegacyModel):

    rating = models.IntegerField()
    title = amo.TranslatedField()
    body = amo.TranslatedField()

    version = models.ForeignKey('versions.Version')
    user = models.ForeignKey(User)
    reply_to = models.ForeignKey('self', db_column='reply_to')

    class Meta:
        db_table = 'reviews'
