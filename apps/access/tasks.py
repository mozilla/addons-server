from celery.task.sets import TaskSet
from celeryutils import task
import logging


log = logging.getLogger('z.task')


@task
def invalidate_users(**kw):
    """Invalidate all users to reflect latest Marketplace access whitelist."""
    from amo.utils import chunked
    from users.models import UserProfile
    log.info('Invalidating users for access whitelist.')
    d = UserProfile.objects.values_list('id', flat=True)
    ts = [_invalidate_users.subtask(args=[chunk]) for chunk in chunked(d, 100)]
    TaskSet(ts).apply_async()


@task
def _invalidate_users(data, **kw):
    from users.models import UserProfile
    log.info('[%s@%s] Invalidating users for access whitelist.' %
             (len(data), _invalidate_users.rate_limit))
    for pk in data:
        UserProfile.objects.get(id=pk).save()
