from decimal import Decimal
import json

import caching

from django.conf import settings
from django.db import models
from django.db.models import F

from olympia import amo
from olympia.amo.models import ModelBase
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.files.models import File


class Config(caching.base.CachingMixin, models.Model):
    """Sitewide settings."""
    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()
    objects = caching.base.CachingManager()

    class Meta:
        db_table = u'config'

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
        return


def set_config(conf, value):
    cf, created = Config.objects.get_or_create(key=conf)
    cf.value = value
    cf.save()


class ValidationJob(ModelBase):
    application = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                              db_column='application_id')
    curr_max_version = models.ForeignKey(AppVersion,
                                         related_name='validation_current_set')
    target_version = models.ForeignKey(AppVersion,
                                       related_name='validation_target_set')
    finish_email = models.EmailField(null=True, max_length=75)
    completed = models.DateTimeField(null=True, db_index=True)
    creator = models.ForeignKey('users.UserProfile', null=True)

    def result_passing(self):
        return self.result_set.exclude(completed=None).filter(errors=0,
                                                              task_error=None)

    def result_completed(self):
        return self.result_set.exclude(completed=None)

    def result_errors(self):
        return self.result_set.exclude(task_error=None)

    def result_failing(self):
        return self.result_set.exclude(completed=None).filter(errors__gt=0)

    @property
    def preview_notify_mail_link(self):
        return self._preview_link(EmailPreviewTopic(self, 'notify'))

    def _preview_link(self, topic):
        qs = topic.filter()
        if qs.count():
            return reverse('zadmin.email_preview_csv', args=[topic.topic])

    def preview_notify_mail(self, *args, **kwargs):
        EmailPreviewTopic(self, 'notify').send_mail(*args, **kwargs)

    def get_notify_preview_emails(self):
        return EmailPreviewTopic(self, 'notify').filter()

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
        self.validation = validation
        results = json.loads(validation)
        compat = results['compatibility_summary']
        # TODO(Kumar) these numbers should not be combined. See bug 657936.
        self.errors = results['errors'] + compat['errors']
        self.warnings = results['warnings'] + compat['warnings']
        self.notices = results['notices'] + compat['notices']
        self.valid = self.errors == 0

        messages = results['messages']
        message_ids = ['.'.join(msg['id']) for msg in messages]

        message_summary = {}

        for message, message_id in zip(messages, message_ids):
            compat_type = message.get('compatibility_type')

            if not compat_type or compat_type != 'error':
                continue

            if message_id not in message_summary:
                message_summary[message_id] = (
                    ValidationResultMessage.objects.get_or_create(
                        message_id=message_id,
                        validation_job=self.validation_job,
                        defaults={
                            'message': message.get('message', ''),
                            'compat_type': compat_type,
                        }
                    )[0]
                )

        for message in message_summary.values():
            # All relevant messages are already created, to avoid
            # any side-effects we run a separate UPDATE query instead
            # of an explicit `.save()` so that the database handles atomic
            # increments for us.
            ValidationResultMessage.objects.filter(pk=message.pk).update(
                addons_affected=F('addons_affected') + 1
            )

            ValidationResultAffectedAddon.objects.create(
                validation_result_message=message,
                addon=self.file.version.addon)


class ValidationResultMessage(ModelBase):
    """Summary of validation result messages"""
    validation_job = models.ForeignKey(ValidationJob,
                                       related_name='message_summary')
    message_id = models.CharField(max_length=256)
    message = models.TextField()
    compat_type = models.CharField(max_length=256)
    addons_affected = models.PositiveIntegerField(default=0)


class ValidationResultAffectedAddon(ModelBase):
    """Link to an add-on that is affected by a specific validation message."""
    addon = models.ForeignKey('addons.Addon')
    validation_result_message = models.ForeignKey(ValidationResultMessage)


class EmailPreviewTopic(object):
    """Store emails in a given topic so an admin can preview before
    re-sending.

    A topic is a unique string identifier that groups together preview emails.
    If you pass in an object (a Model instance) you will get a poor man's
    foreign key as your topic.

    For example, EmailPreviewTopic(addon) will link all preview emails to
    the ID of that addon object.
    """

    def __init__(self, object=None, suffix='', topic=None):
        if not topic:
            assert object, 'object keyword is required when topic is empty'
            topic = '%s-%s-%s' % (object.__class__._meta.db_table, object.pk,
                                  suffix)
        self.topic = topic

    def filter(self, *args, **kw):
        kw['topic'] = self.topic
        return EmailPreview.objects.filter(**kw)

    def send_mail(self, subject, body,
                  from_email=settings.DEFAULT_FROM_EMAIL,
                  recipient_list=tuple([])):
        return EmailPreview.objects.create(
            topic=self.topic,
            subject=subject, body=body,
            recipient_list=u','.join(recipient_list),
            from_email=from_email)


class EmailPreview(ModelBase):
    """A log of emails for previewing purposes.

    This is only for development and the data might get deleted at any time.
    """
    topic = models.CharField(max_length=255, db_index=True)
    recipient_list = models.TextField()  # comma separated list of emails
    from_email = models.EmailField(max_length=75)
    subject = models.CharField(max_length=255)
    body = models.TextField()

    class Meta:
        db_table = 'email_preview'


class SiteEvent(models.Model):
    """Information records about downtime, releases, and other pertinent
       events on the site."""

    SITE_EVENT_CHOICES = amo.SITE_EVENT_CHOICES.items()

    start = models.DateField(db_index=True,
                             help_text='The time at which the event began.')
    end = models.DateField(
        db_index=True, null=True, blank=True,
        help_text='If the event was a range, the time at which it ended.')
    event_type = models.PositiveIntegerField(choices=SITE_EVENT_CHOICES,
                                             db_index=True, default=0)
    description = models.CharField(max_length=255, blank=True, null=True)
    # An outbound link to an explanatory blog post or bug.
    more_info_url = models.URLField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'zadmin_siteevent'


class DownloadSource(models.Model):
    # e.g., `mkt-search` or `mkt-detail-`.
    name = models.CharField(max_length=255)

    # e.g., `full` or `prefix`.
    type = models.CharField(max_length=255)

    description = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'download_sources'

    def __unicode__(self):
        return u'%s (%s)' % (self.name, self.type)
