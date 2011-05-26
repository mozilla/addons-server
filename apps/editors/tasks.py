from django.conf import settings

import commonware.log
import celery.task
from celeryutils import task
from hera.contrib.django_utils import flush_urls

from devhub.models import ActivityLog, CommentLog

log = commonware.log.getLogger('z.task')


# We use celery.task.ping in /monitor, so we need it to return results.
celery.task.PingTask.ignore_result = False


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
