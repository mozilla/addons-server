import olympia.core.logger

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on
from olympia.amo.utils import resize_image, SafeStorage

from .models import UserProfile


task_log = olympia.core.logger.getLogger('z.task')


@task
def delete_photo(dst, **kw):
    task_log.info('[1@None] Deleting photo: %s.' % dst)

    try:
        SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics').delete(dst)
    except Exception as e:
        task_log.error('Error deleting userpic: %s' % e)


@task
@set_modified_on
def resize_photo(src, dst, locally=False, **kw):
    """Resizes userpics to 200x200"""
    task_log.info('[1@None] Resizing photo: %s' % dst)

    try:
        resize_image(src, dst, (200, 200))
        return True
    except Exception as e:
        task_log.error('Error saving userpic: %s' % e)


@task(rate_limit='15/m')
def update_user_ratings_task(data, **kw):
    task_log.info(
        "[%s@%s] Updating add-on author's ratings."
        % (len(data), update_user_ratings_task.rate_limit)
    )
    for pk, rating in data:
        UserProfile.objects.filter(pk=pk).update(averagerating=round(float(rating), 2))


@task
def backfill_activity_and_iplog(ids):
    task_log.info(
        'Backfilling activity and iplog for users %d-%d [%d]', ids[0], ids[-1], len(ids)
    )
    users = UserProfile.objects.filter(id__in=ids)
    for user in users:
        with core.override_remote_addr(user.last_login_ip):
            ActivityLog.create(amo.LOG.LOG_IN, user=user, created=user.last_login)

        for restriction_history in user.restriction_history.all():
            with core.override_remote_addr(restriction_history.ip_address):
                ActivityLog.create(
                    amo.LOG.RESTRICTED,
                    user=user,
                    details={
                        'restriction': restriction_history.get_restriction_display()
                    },
                    created=restriction_history.created,
                )
