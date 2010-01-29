import amo.models
from translations.fields import TranslatedField


class CannedResponse(amo.models.ModelBase):

    name = TranslatedField()
    response = TranslatedField()

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)
