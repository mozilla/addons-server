from django.core.files.storage import default_storage as storage

import basket

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.utils import resize_image

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
        resize_image(src, dst, (200, 200))
        return True
    except Exception, e:
        task_log.error("Error saving userpic: %s" % e)


@task(rate_limit='15/m')
def update_user_ratings_task(data, **kw):
    task_log.info("[%s@%s] Updating add-on author's ratings." %
                  (len(data), update_user_ratings_task.rate_limit))
    for pk, rating in data:
        UserProfile.objects.filter(pk=pk).update(
            averagerating=round(rating, 2))


@task(rate_limit='250/m')
def sync_user_with_basket(user_profile_id):
    user = UserProfile.objects.get(pk=user_profile_id)
    if user.basket_token:
        return

    try:
        data = basket.lookup_user(user.email)
        user.update(basket_token=data['token'])
        return True
    except Exception as exc:
        acceptable_errors = (
            basket.errors.BASKET_INVALID_EMAIL,
            basket.errors.BASKET_UNKNOWN_EMAIL)

        if getattr(exc, 'code', None) not in acceptable_errors:
            task_log.exception(
                'sync_user_with_basket() failed with error: {}, retrying'
                .format(exc))
            return sync_user_with_basket.retry(exc=exc, max_retries=3)
