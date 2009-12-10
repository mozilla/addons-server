from django.db import models

import amo
from translations.fields import TranslatedField
from users.models import User


class Review(amo.ModelBase):

    rating = models.IntegerField()
    title = TranslatedField()
    body = TranslatedField()

    version = models.ForeignKey('versions.Version')
    user = models.ForeignKey(User)
    reply_to = models.ForeignKey('self', db_column='reply_to')

    class Meta:
        db_table = 'reviews'
