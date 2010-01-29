from django.db import models

import amo.models
from translations.fields import TranslatedField


class Application(amo.models.ModelBase):

    guid = models.CharField(max_length=255, default='')
    name = TranslatedField()
    shortname = TranslatedField()
    # icondata
    # icontype = models.CharField(max_length=25, default='')

    class Meta:
        db_table = 'applications'

    def __unicode__(self):
        return unicode(self.name)


class AppVersion(amo.models.ModelBase):

    application = models.ForeignKey(Application)
    version = models.CharField(max_length=255, default='')
    version_int = models.IntegerField(editable=False)
    # TODO: 1.2
    # version_int = models.BigIntegerField()

    class Meta:
        db_table = 'appversions'

    def __unicode__(self):
        return self.version
