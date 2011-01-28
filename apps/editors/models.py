import os

from django.conf import settings
from django.db import connection, models
from django.db.models.signals import post_syncdb
from tower import ugettext_lazy as _

import amo
import amo.models
from translations.fields import TranslatedField


class CannedResponse(amo.models.ModelBase):

    name = TranslatedField()
    response = TranslatedField()

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)


def _create_view(migration_file):
    cursor = connection.cursor()
    ddl = os.path.join(settings.ROOT, 'migrations',
                       migration_file)
    with open(ddl, 'r') as f:
        cursor.execute(f.read())


class ViewQueue(models.Model):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()
    # id is Addon ID.
    addon_name = models.CharField(max_length=255, verbose_name=_(u'Addon'))
    addon_status = models.PositiveIntegerField(choices=STATUS_CHOICES)
    addon_type_id = models.PositiveIntegerField(verbose_name=_(u'Type'))
    admin_review = models.BooleanField()
    is_site_specific = models.BooleanField()
    waiting_time_days = models.PositiveIntegerField(
                                    verbose_name=_(u'Waiting Time'))
    waiting_time_hours = models.PositiveIntegerField()
    _latest_version_ids = models.CharField(max_length=255,
                                           db_column='latest_version_ids')
    _latest_versions = models.CharField(max_length=255,
                                        db_column='latest_versions')
    _file_platform_ids = models.CharField(max_length=255,
                                          db_column='file_platform_ids')
    _application_ids = models.CharField(max_length=255,
                                        db_column='application_ids')

    @property
    def latest_version(self):
        return self._explode_concat(self._latest_versions, sep='&&&&',
                                    cast=unicode)[0]

    @property
    def latest_version_id(self):
        return self._explode_concat(self._latest_version_ids)[0]

    @property
    def file_platform_ids(self):
        return self._explode_concat(self._file_platform_ids)

    @property
    def application_ids(self):
        return self._explode_concat(self._application_ids)

    def _explode_concat(self, value, sep=',', cast=int):
        """Returns list of IDs in a MySQL GROUP_CONCAT(field) result."""
        if value is None:
            # for NULL fields, ala left joins
            return []
        return [cast(i) for i in value.split(sep)]

    class Meta:
        abstract = True
        managed = False


class ViewPendingQueue(ViewQueue):

    class Meta(ViewQueue.Meta):
        db_table = 'view_ed_pending_q'


def create_view_ed_pending_q(sender, **kw):
    _create_view('134-view_ed_pending_q.sql')


post_syncdb.connect(create_view_ed_pending_q)


class ViewFullReviewQueue(ViewQueue):

    class Meta(ViewQueue.Meta):
        db_table = 'view_ed_full_review_q'


def create_view_ed_full_review_q(sender, **kw):
    _create_view('135-view_ed_full_review_q.sql')


post_syncdb.connect(create_view_ed_full_review_q)
