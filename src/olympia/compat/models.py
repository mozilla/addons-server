from django.db import models

from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase


class CompatReport(ModelBase):
    guid = models.CharField(max_length=128)
    version = models.CharField(max_length=128)
    app_guid = models.CharField(max_length=128)
    app_version = models.CharField(max_length=128)
    app_build = models.CharField(max_length=128)
    client_os = models.CharField(max_length=128)
    client_ip = models.CharField(max_length=128)
    comments = models.TextField()
    other_addons = JSONField()
    works_properly = models.BooleanField(default=False)
    app_multiprocess_enabled = models.BooleanField(default=False)
    multiprocess_compatible = models.NullBooleanField(default=None)

    class Meta:
        db_table = 'compatibility_reports'

    @classmethod
    def get_counts(self, guid):
        works = dict(
            CompatReport.objects.filter(guid=guid)
            .values_list('works_properly')
            .annotate(models.Count('id'))
        )
        return {'success': works.get(True, 0), 'failure': works.get(False, 0)}


class AppCompat(ModelBase):
    """
    Stub model for use with search. The schema:

        {id: addon.id,
         name: addon.name,
         slug: addon.slug,
         guid: addon.guid,
         current_version: {id: version int, version: version string},
         binary: addon.binary_components,
         count: total # of update counts,
         top_95_all: {APP.id: bool},
         top_95: {APP.id: {version int: bool}},
         works: {APP.id: {version int: {success: int, failure: int, total: int,
                                        failure_ratio: float}}},
         max_version: {APP.id: version string},
         usage: {APP.id: addon.daily_usage},
         support: {APP.id: {max: version int, min: version int},
        }
    """

    class Meta:
        abstract = True
        db_table = 'compat'


class CompatTotals(ModelBase):
    """
    Cache for totals of success/failure reports.
    """

    total = models.PositiveIntegerField()

    class Meta:
        db_table = 'compat_totals'
