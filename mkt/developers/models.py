from django.db import models

import amo
from devhub.models import ActivityLog
from mkt.webapps.models import Webapp


class AppLog(amo.models.ModelBase):
    """
    This table is for indexing the activity log by app.
    """
    addon = models.ForeignKey(Webapp)
    activity_log = models.ForeignKey(ActivityLog)

    class Meta:
        db_table = 'log_activity_app'
        ordering = ('-created',)
