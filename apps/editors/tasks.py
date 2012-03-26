from django.conf import settings

import commonware.log
import celery.task
from celeryutils import task
from hera.contrib.django_utils import flush_urls

from devhub.models import ActivityLog, CommentLog, VersionLog
from versions.models import Version

log = commonware.log.getLogger('z.task')


# We use celery.task.ping in /monitor, so we need it to return results.
# celery.task.PingTask.ignore_result = False

# TODO(Kumar) This moved to celery.task.control.ping after migrating to 2.5.
# Do we still need to patch the result?


@task
def add_commentlog(items, **kw):
    log.info('[%s@%s] Adding CommentLog starting with ActivityLog: %s' %
             (len(items), add_commentlog.rate_limit, items[0]))


    for al in ActivityLog.objects.filter(pk__in=items):
        # Delete existing entries:
        CommentLog.objects.filter(activity_log=al).delete()

        # Create a new entry:
        if 'comments' in al.details:
            CommentLog(comments=al.details['comments'], activity_log=al).save()


@task
def add_versionlog(items, **kw):
    log.info('[%s@%s] Adding VersionLog starting with ActivityLog: %s' %
             (len(items), add_versionlog.rate_limit, items[0]))

    for al in ActivityLog.objects.filter(pk__in=items):
        # Delete existing entries:
        VersionLog.objects.filter(activity_log=al).delete()

        for a in al.arguments:
            if isinstance(a, Version):
                vl = VersionLog(version=a, activity_log=al)
                vl.save()
                # We need to save it twice to backdate the created date.
                vl.created = al.created
                vl.save()

