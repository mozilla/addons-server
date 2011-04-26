from decimal import Decimal
import json

from django.db import models
from django.utils.functional import memoize

import amo
import amo.models
from applications.models import Application, AppVersion
from files.models import FileValidation

_config_cache = {}


class Config(models.Model):
    """Sitewide settings."""
    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = u'config'

    @property
    def json(self):
        return json.loads(self.value)


def get_config(conf):
    try:
        c = Config.objects.get(key=conf)
        return c.value
    except Config.DoesNotExist:
        return

get_config = memoize(get_config, _config_cache, 1)


def set_config(conf, value):
    cf, created = Config.objects.get_or_create(key=conf)
    cf.value = value
    cf.save()
    _config_cache.clear()


class ValidationJob(amo.models.ModelBase):
    application = models.ForeignKey(Application)
    curr_max_version = models.ForeignKey(AppVersion,
                                         related_name='validation_current_set')
    target_version = models.ForeignKey(AppVersion,
                                       related_name='validation_target_set')
    finish_email = models.CharField(max_length=255, null=True)
    completed = models.DateTimeField(null=True, db_index=True)

    @amo.cached_property
    def stats(self):
        total = self.result_set.count()
        completed = self.result_set.exclude(completed=None).count()
        passing = (self.result_set.exclude(completed=None)
                   .filter(file_validation__errors=0).count())
        # TODO(Kumar) count exceptions here?
        return {
            'number_of_addons': total,
            'passing_addons': passing,
            'failing_addons': total - passing,
            'percent_complete': ((Decimal(total) / Decimal(completed))
                                 * Decimal(100)
                                 if (total and completed) else 0)
        }

    class Meta:
        db_table = 'validation_job'


class ValidationResult(amo.models.ModelBase):
    validation_job = models.ForeignKey(ValidationJob,
                                       related_name='result_set')
    file_validation = models.ForeignKey(FileValidation, null=True)
    task_error = models.TextField(null=True)
    completed = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'validation_result'
