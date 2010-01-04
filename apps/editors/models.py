from django.db import models

import amo
from translations.fields import TranslatedField


class CannedResponse(amo.ModelBase):

    name = TranslatedField()
    response = TranslatedField()

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)
