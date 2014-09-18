from decimal import Decimal
import json

from django.core.cache import cache
from django.conf import settings
from django.db import models
from django.utils.functional import memoize

import amo
import amo.models
from amo.urlresolvers import reverse
from applications.models import AppVersion
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
        try:
            return json.loads(self.value)
        except (TypeError, ValueError):
            return {}


def unmemoized_get_config(conf):
    try:
        c = Config.objects.get(key=conf)
        return c.value
    except Config.DoesNotExist:
        return

get_config = memoize(unmemoized_get_config, _config_cache, 1)


def set_config(conf, value):
    cf, created = Config.objects.get_or_create(key=conf)
    cf.value = value
    cf.save()
    _config_cache.clear()


class ValidationJob(amo.models.ModelBase):
    application = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                              db_column='application_id')
    curr_max_version = models.ForeignKey(AppVersion,
                                         related_name='validation_current_set')
    target_version = models.ForeignKey(AppVersion,
                                       related_name='validation_target_set')
    finish_email = models.EmailField(null=True)
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
        self.validation = validation
        results = json.loads(validation)
        compat = results['compatibility_summary']
        # TODO(Kumar) these numbers should not be combined. See bug 657936.
        self.errors = results['errors'] + compat['errors']
        self.warnings = results['warnings'] + compat['warnings']
        self.notices = results['notices'] + compat['notices']
        self.valid = self.errors == 0


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


class EmailPreview(amo.models.ModelBase):
    """A log of emails for previewing purposes.

    This is only for development and the data might get deleted at any time.
    """
    topic = models.CharField(max_length=255, db_index=True)
    recipient_list = models.TextField()  # comma separated list of emails
    from_email = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField()

    class Meta:
        db_table = 'email_preview'


class ValidationJobTally(object):
    """Redis key/vals for a tally of validation job results.

    The key/val pairs look like this::

        # message keys that were found by this validation job:
        validation.job_id:1234:msg_keys = set([
            'path.to.javascript_data_urls',
            'path.to.navigator_language'
            ])

        # translation of message keys to actual messages:
        validation.msg_key:<msg_key>:message =
            'javascript:/data: URIs may be incompatible with Firefox 6'
        validation.msg_key:<msg_key>:long_message =
            'A more detailed message....'

        # type of message (error, warning, or notice)
        validation.msg_key:<msg_key>:type = 'error'

        # count of addons affected per message key, per job
        validation.job_id:1234.msg_key:<msg_key>:addons_affected = 120

    """

    def __init__(self, job_id):
        self.job_id = job_id

    def get_messages(self):
        for msg_key in cache.get('validation.job_id:%s' % self.job_id):
            d = cache.get('validation.msg_key:%s' % (msg_key,))
            d['key'] = msg_key
            d['addons_affected'] = cache.get(
                'validation.job_id:%s.msg_key:%s:addons_affected'
                % (self.job_id, msg_key))
            yield d

    def save_messages(self, msgs):
        msg_ids = ['.'.join(msg['id']) for msg in msgs]
        cache.set('validation.job_id:%s' % self.job_id, msg_ids)
        for msg, key in zip(msgs, msg_ids):
            if isinstance(msg['description'], list):
                des = []
                for _m in msg['description']:
                    if isinstance(_m, list):
                        for x in _m:
                            des.append(x)
                    else:
                        des.append(_m)
                des = '; '.join(des)
            else:
                des = msg['description']
            cache.set('validation.msg_key:' + key,
                      {'long_message': des,
                       'message': msg['message'],
                       'type': msg.get('compatibility_type',
                                       msg.get('type'))
                       })
            aa = ('validation.job_id:%s.msg_key:%s:addons_affected'
                  % (self.job_id, key))
            try:
                cache.incr(aa)
            except ValueError:
                cache.set(aa, 1)


class SiteEvent(models.Model):
    """Information records about downtime, releases, and other pertinent
       events on the site."""

    SITE_EVENT_CHOICES = amo.SITE_EVENT_CHOICES.items()

    start = models.DateField(db_index=True,
                             help_text='The time at which the event began.')
    end = models.DateField(db_index=True, null=True, blank=True,
        help_text='If the event was a range, the time at which it ended.')
    event_type = models.PositiveIntegerField(choices=SITE_EVENT_CHOICES,
                                             db_index=True, default=0)
    description = models.CharField(max_length=255, blank=True, null=True)
    # An outbound link to an explanatory blog post or bug.
    more_info_url = models.URLField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = ('zadmin_siteevent' +
                    settings.EVENT_TABLE_SUFFIX)


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
