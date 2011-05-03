from decimal import Decimal
import json

from django.db import models
from django.utils.functional import memoize

import amo
import amo.models
from applications.models import Application, AppVersion
from files.models import File

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

    def result_passing(self):
        return self.result_set.exclude(completed=None).filter(errors=0)

    def result_completed(self):
        return self.result_set.exclude(completed=None)

    def result_errors(self):
        return self.result_set.exclude(task_error=None)

    @amo.cached_property
    def stats(self):
        total = self.result_set.count()
        completed = self.result_completed().count()
        passing = self.result_passing().count()
        errors = self.result_errors().count()
        return {
            'total': total,
            'completed': completed,
            'passing': passing,
            'failing': completed - passing,
            'errors': errors,
            'percent_complete': (Decimal(completed) / Decimal(total)
                                 * Decimal(100)
                                 if (total and completed) else 0),
        }

    class Meta:
        db_table = 'validation_job'


class ValidationResult(amo.models.ModelBase):
    """Result of a single validation task based on the addon file.

    This is different than FileValidation because it allows multiple
    validation results per file.
    """
    validation_job = models.ForeignKey(ValidationJob,
                                       related_name='result_set')
    file = models.ForeignKey(File, related_name='validation_results')
    valid = models.BooleanField(default=False)
    errors = models.IntegerField(default=0, null=True)
    warnings = models.IntegerField(default=0, null=True)
    notices = models.IntegerField(default=0, null=True)
    validation = models.TextField(null=True)
    task_error = models.TextField(null=True)
    completed = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'validation_result'

    def apply_validation(self, validation):
        js = json.loads(validation)
        self.validation = validation
        self.errors = js['errors']
        self.warnings = js['warnings']
        self.notices = js['notices']
        self.valid = self.errors == 0
