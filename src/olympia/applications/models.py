from django.db import models

from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ModelBase
from olympia.constants.applications import APPS_CHOICES
from olympia.versions import compare


class AppVersion(ModelBase):
    id = PositiveAutoField(primary_key=True)
    application = models.PositiveIntegerField(choices=APPS_CHOICES,
                                              db_column='application_id')
    version = models.CharField(max_length=255, default='')
    version_int = models.BigIntegerField(editable=False)

    class Meta:
        db_table = 'appversions'
        ordering = ['-version_int']
        indexes = [
            models.Index(fields=('application',),
                         name='application_id'),
            models.Index(fields=('version',), name='version'),
            models.Index(fields=('version_int',), name='version_int_idx'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('application', 'version'),
                                    name='application_id_2'),
        ]

    def save(self, *args, **kw):
        if not self.version_int:
            self.version_int = compare.version_int(self.version)
        return super(AppVersion, self).save(*args, **kw)

    def __str__(self):
        return self.version
