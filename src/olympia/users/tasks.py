import csv
import itertools
import tempfile

from django.conf import settings

import requests
from requests.exceptions import HTTPError, Timeout

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.utils import (
    SafeStorage,
    backup_storage_enabled,
    copy_file_to_backup_storage,
    resize_image,
)

from .models import BannedUserContent, EmailBlock, UserProfile


task_log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def delete_photo(pk, **kw):
    task_log.info('[1@None] Deleting photo for user: %s.' % pk)

    user = UserProfile.objects.get(pk=pk)
    storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
    banned = kw.get('banned') or user.banned
    if user.picture_type and banned:
        if backup_storage_enabled() and storage.exists(user.picture_path_original):
            # When deleting a picture as part of a ban, we keep a copy of the
            # original picture for the duration of the potential appeal process.
            picture_backup_name = copy_file_to_backup_storage(
                user.picture_path_original, user.picture_type
            )
            task_log.info(
                'Copied picture for banned user %s to %s', pk, picture_backup_name
            )
            BannedUserContent.objects.update_or_create(
                user=user,
                defaults={
                    'picture_backup_name': picture_backup_name,
                    'picture_type': user.picture_type,
                },
            )
        user.update(picture_type=None)
    storage.delete(user.picture_path)
    storage.delete(user.picture_path_original)


@task
@set_modified_on
def resize_photo(src, dst, **kw):
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


BATCH_SIZE = 100


@task(autoretry_for=(HTTPError, Timeout), max_retries=5, retry_backoff=True)
def sync_blocked_emails(batch_size=BATCH_SIZE, **kw):
    url = (
        f'{settings.SOCKET_LABS_HOST}/servers/{settings.SOCKET_LABS_SERVER_ID}/'
        'suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc'
    )
    headers = {
        'authorization': f'Bearer {settings.SOCKET_LABS_TOKEN}',
    }
    response = requests.get(url, headers=headers)

    # Raise exception if not 200 like response
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(
        dir=settings.TMP_PATH, delete=not settings.DEBUG, mode='w+b'
    ) as csv_file:
        csv_file.write(response.content)
        csv_file.seek(0)

        with open(csv_file.name, 'r') as f:
            csv_suppression_list = csv.reader(f)

            next(csv_suppression_list)

            while True:
                batch = list(itertools.islice(csv_suppression_list, batch_size))

                if not batch:
                    break

                email_blocks = [EmailBlock(email=record[3]) for record in batch]
                EmailBlock.objects.bulk_create(email_blocks, ignore_conflicts=True)
