import os

from datetime import datetime

from django.db import models
from django.conf import settings

import amo.models


class DiscoveryModule(amo.models.ModelBase):
    """
    Keeps the application, ordering, and locale metadata for a module.

    The modules are defined statically in modules.py and linked to a database
    row through the module's name.
    """
    app = models.ForeignKey('applications.Application')
    module = models.CharField(max_length=255)
    ordering = models.IntegerField(null=True, blank=True)
    locales = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'discovery_modules'
