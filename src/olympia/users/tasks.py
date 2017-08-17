from django.core.files.storage import default_storage as storage

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on
from olympia.amo.utils import resize_image
from olympia.amo.templatetags.jinja_helpers import user_media_path


from .models import UserProfile

task_log = olympia.core.logger.getLogger('z.task')


@task
def delete_photo(dst, **kw):
    task_log.debug('[1@None] Deleting photo: %s.' % dst)

    if not dst.startswith(user_media_path('userpics')):
        task_log.error("Someone tried deleting something they shouldn't: %s"
                       % dst)
        return

    try:
        storage.delete(dst)
    except Exception, e:
        task_log.error("Error deleting userpic: %s" % e)


@task
@set_modified_on
def resize_photo(src, dst, locally=False, **kw):
    """Resizes userpics to 200x200"""
    task_log.debug('[1@None] Resizing photo: %s' % dst)

    try:
        resize_image(src, dst, (200, 200), locally=locally)
        return True
    except Exception, e:
        task_log.error("Error saving userpic: %s" % e)


@task(rate_limit='15/m')
def update_user_ratings_task(data, **kw):
    task_log.info("[%s@%s] Updating add-on author's ratings." %
                  (len(data), update_user_ratings_task.rate_limit))
    for pk, rating in data:
        rating = "%.2f" % round(rating, 2)
        UserProfile.objects.filter(pk=pk).update(averagerating=rating)
