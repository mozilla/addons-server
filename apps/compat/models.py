from django.db import models

import json_field

import amo
import amo.models


class CompatReport(amo.models.ModelBase):
    guid = models.CharField(max_length=128)
    version = models.CharField(max_length=128)
    app_guid = models.CharField(max_length=128)
    app_version = models.CharField(max_length=128)
    app_build = models.CharField(max_length=128)
    client_os = models.CharField(max_length=128)
    client_ip = models.CharField(max_length=128)
    comments = models.TextField()
    other_addons = json_field.JSONField()
    works_properly = models.BooleanField()

    class Meta:
        db_table = 'compatibility_reports'

    @classmethod
    def get_counts(self, guid):
        works = dict(CompatReport.objects.filter(guid=guid)
                     .values_list('works_properly')
                     .annotate(models.Count('id')))
        return {
            'success': works.get(True, 0),
            'failure': works.get(False, 0)
        }


class AppCompat(amo.models.ModelBase):
    """
    Stub model for use with search. The schema:

        {id: addon.id,
         name: addon.name,
         slug: addon.slug,
         guid: addon.guid,
         self_hosted: addon.is_selfhosted,
         current_version: version string,
         current_version_id: version int,
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


class CompatTotals(amo.models.ModelBase):
    """
    Cache for totals of success/failure reports.
    """
    app = models.PositiveIntegerField()
    total = models.PositiveIntegerField()

    class Meta:
        db_table = 'compat_totals'
