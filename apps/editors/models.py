import os

from django.conf import settings
from django.db import connection, models
from django.db.models.signals import post_syncdb
from tower import ugettext_lazy as _

import amo.models
from translations.fields import TranslatedField


class CannedResponse(amo.models.ModelBase):

    name = TranslatedField()
    response = TranslatedField()

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)


class ViewEditorQueue(models.Model):
    # id is Addon ID.
    version_id = models.PositiveIntegerField()
    addon_name = models.CharField(max_length=255)
    addon_type_id = models.PositiveIntegerField()
    admin_review = models.BooleanField()
    is_site_specific = models.BooleanField()
    platform_id = models.PositiveIntegerField()
    days_since_created = models.PositiveIntegerField()
    hours_since_created = models.PositiveIntegerField()
    days_since_nominated = models.PositiveIntegerField(null=True)
    hours_since_nominated = models.PositiveIntegerField(null=True)
    applications = models.CharField(max_length=255)
    # version_apps = models.CharField(max_length=255)
    # version_min = models.CharField(max_length=255)
    # version_max = models.CharField(max_length=255)

    class Meta:
        db_table = 'view_editor_queue'
        managed = False


def create_view(sender, **kw):
    cursor = connection.cursor()
    ddl = os.path.join(settings.ROOT, 'migrations',
                       '129-view-editor-queue.sql')
    with open(ddl, 'r') as f:
        cursor.execute(f.read())


post_syncdb.connect(create_view)
