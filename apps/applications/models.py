from django.db import models

import amo.models
from versions import compare


class Application(amo.models.ModelBase):

    guid = models.CharField(max_length=255, default='')
    # We never reference these translated fields, so stop loading them.
    # name = TranslatedField()
    # shortname = TranslatedField()
    # icondata
    # icontype = models.CharField(max_length=25, default='')

    class Meta:
        db_table = 'applications'

    def __unicode__(self):
        return unicode(amo.APPS_ALL[self.id].pretty)


class AppVersion(amo.models.ModelBase):

    application = models.ForeignKey(Application)
    version = models.CharField(max_length=255, default='')
    version_int = models.BigIntegerField(editable=False)

    class Meta:
        db_table = 'appversions'
        ordering = ['-version_int']

    def save(self, *args, **kw):
        if not self.version_int:
            self.version_int = compare.version_int(self.version)
        return super(AppVersion, self).save(*args, **kw)

    def __init__(self, *args, **kwargs):
        super(AppVersion, self).__init__(*args, **kwargs)
        # Add all the major, minor, ..., version attributes to the object.
        self.__dict__.update(compare.version_dict(self.version or ''))

    def __unicode__(self):
        return self.version

    def flush_urls(self):
        return ['*/pages/appversions/*']
