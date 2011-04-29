from django.db import models

import json_field

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
