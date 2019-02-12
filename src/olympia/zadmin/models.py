import json

from decimal import Decimal

from django.db import models
from django.utils.encoding import python_2_unicode_compatible

from olympia import amo
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ModelBase
from olympia.applications.models import AppVersion
from olympia.files.models import File


@python_2_unicode_compatible
class Config(models.Model):
    """Sitewide settings."""
    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = u'config'

    def __str__(self):
        return self.key

    @property
    def json(self):
        try:
            return json.loads(self.value)
        except (TypeError, ValueError):
            return {}


def get_config(conf):
    try:
        return Config.objects.get(key=conf).value
    except Config.DoesNotExist:
        return None


def set_config(conf, value):
    cf, created = Config.objects.get_or_create(key=conf)
    cf.value = value
    cf.save()


class ValidationJob(ModelBase):
    id = PositiveAutoField(primary_key=True)
    application = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                              db_column='application_id')
    curr_max_version = models.ForeignKey(
        AppVersion, related_name='validation_current_set',
        on_delete=models.CASCADE)
    target_version = models.ForeignKey(
        AppVersion, related_name='validation_target_set',
        on_delete=models.CASCADE)
    finish_email = models.EmailField(null=True, max_length=75)
    completed = models.DateTimeField(null=True, db_index=True)
    creator = models.ForeignKey(
        'users.UserProfile', null=True, on_delete=models.CASCADE)

    def result_passing(self):
        return self.result_set.exclude(completed=None).filter(errors=0,
                                                              task_error=None)

    def result_completed(self):
        return self.result_set.exclude(completed=None)

    def result_errors(self):
        return self.result_set.exclude(task_error=None)

    def result_failing(self):
        return self.result_set.exclude(completed=None).filter(errors__gt=0)

    def is_complete(self, as_int=False):
        completed = self.completed is not None
        if as_int:
            return 1 if completed else 0
        else:
            return completed

    @property
    def stats(self):
        if not hasattr(self, '_stats'):
            self._stats = self._count_stats()
        return self._stats

    def _count_stats(self):
        total = self.result_set.count()
        completed = self.result_completed().count()
        passing = self.result_passing().count()
        errors = self.result_errors().count()
        failing = self.result_failing().count()
        return {
            'job_id': self.pk,
            'total': total,
            'completed': completed,
            'completed_timestamp': str(self.completed or ''),
            'passing': passing,
            'failing': failing,
            'errors': errors,
            'percent_complete': (
                Decimal(completed) / Decimal(total) * Decimal(100)
                if (total and completed) else 0),
        }

    class Meta:
        db_table = 'validation_job'


class ValidationResult(ModelBase):
    """Result of a single validation task based on the addon file.

    This is different than FileValidation because it allows multiple
    validation results per file.
    """
    id = PositiveAutoField(primary_key=True)
    validation_job = models.ForeignKey(
        ValidationJob, related_name='result_set', on_delete=models.CASCADE)
    file = models.ForeignKey(
        File, related_name='validation_results', on_delete=models.CASCADE)
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
        self.validation = validation
        results = json.loads(validation)
        compat = results['compatibility_summary']
        # TODO(Kumar) these numbers should not be combined. See bug 657936.
        self.errors = results['errors'] + compat['errors']
        self.warnings = results['warnings'] + compat['warnings']
        self.notices = results['notices'] + compat['notices']
        self.valid = self.errors == 0
