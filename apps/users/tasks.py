import commonware.log
from celery.decorators import task

from . import cron

from django.contrib.auth.models import User as DjangoUser
from users.models import UserProfile

task_log = commonware.log.getLogger('z.task')

@task(rate_limit='10/m')
def _delete_users(data, **kw):
    """Feed me a list of user ids you want to delete from the database.  This
    isn't a flag, it actually deletes rows."""

    task_log.info("[%s@%s] Bulk deleting users" %
                   (len(data), _delete_users.rate_limit))

    UserProfile.objects.filter(pk__in=data).delete()
    DjangoUser.objects.filter(pk__in=data).delete()
