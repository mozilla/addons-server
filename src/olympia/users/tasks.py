import csv
import datetime
import itertools
import tempfile
import urllib.parse

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext

import requests
from celery.exceptions import Retry
from requests.exceptions import HTTPError, Timeout

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.utils import (
    SafeStorage,
    backup_storage_enabled,
    copy_file_to_backup_storage,
    resize_image,
    send_mail_jinja,
)

from .models import (
    BannedUserContent,
    SuppressedEmail,
    SuppressedEmailVerification,
    UserProfile,
)


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


def assert_socket_labs_settings_defined():
    if not settings.SOCKET_LABS_TOKEN:
        raise Exception('SOCKET_LABS_TOKEN is not defined')

    if not settings.SOCKET_LABS_HOST:
        raise Exception('SOCKET_LABS_HOST is not defined')

    if not settings.SOCKET_LABS_SERVER_ID:
        raise Exception('SOCKET_LABS_SERVER_ID is not defined')


@task(autoretry_for=(HTTPError, Timeout), max_retries=5, retry_backoff=True)
def sync_blocked_emails(batch_size=BATCH_SIZE, **kw):
    assert_socket_labs_settings_defined()

    path = f'servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download'
    params = {'sortField': 'suppressionLastUpdate', 'sortDirection': 'dsc'}
    url = (
        urllib.parse.urljoin(settings.SOCKET_LABS_HOST, path)
        + '?'
        + urllib.parse.urlencode(params)
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

                email_blocks = [SuppressedEmail(email=record[3]) for record in batch]
                SuppressedEmail.objects.bulk_create(email_blocks, ignore_conflicts=True)


@task(autoretry_for=(HTTPError, Timeout), max_retries=5, retry_backoff=True)
def send_suppressed_email_confirmation(suppressed_email_verification_id):
    assert_socket_labs_settings_defined()

    verification = SuppressedEmailVerification.objects.filter(
        id=suppressed_email_verification_id
    ).first()

    if not verification:
        raise Exception(f'invalid id: {suppressed_email_verification_id}')

    email = verification.suppressed_email.email

    path = f'servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/remove'
    params = {
        'emailAddress': email,
    }

    url = (
        urllib.parse.urljoin(settings.SOCKET_LABS_HOST, path)
        + '?'
        + urllib.parse.urlencode(params)
    )
    headers = {
        'authorization': f'Bearer {settings.SOCKET_LABS_TOKEN}',
    }

    task_log.info(f'removing email: {email} from suppression list')
    response = requests.delete(url, headers=headers)
    if response.status_code == 404:
        task_log.warn(f'email not found in suppression list: {email}')
    else:
        response.raise_for_status()

    code_snippet = str(verification.confirmation_code)[-5:]

    verification.status = SuppressedEmailVerification.STATUS_CHOICES.Pending

    confirmation_link = (
        reverse('devhub.email_verification')
        + '?code='
        + str(verification.confirmation_code)
    )

    send_mail_jinja(
        gettext(f'Verify your email ({code_snippet})'),
        'devhub/emails/verify-email-requested.ltxt',
        {
            'confirmation_link': confirmation_link,
        },
        recipient_list=[email],
    )

    verification.save()
    check_suppressed_email_confirmation.delay(verification.id)


@task(
    autoretry_for=(
        HTTPError,
        Timeout,
    ),
    max_retries=5,
    retry_backoff=True,
)
def check_suppressed_email_confirmation(suppressed_email_verification_id, page_size=5):
    assert_socket_labs_settings_defined()

    verification = SuppressedEmailVerification.objects.filter(
        id=suppressed_email_verification_id
    ).first()

    if not verification:
        raise Exception(f'invalid id: {suppressed_email_verification_id}')

    email = verification.suppressed_email.email

    current_count = 0
    total = 0

    code_snippet = str(verification.confirmation_code)[-5:]
    path = f'servers/{settings.SOCKET_LABS_SERVER_ID}/reports/recipient-search/'

    # socketlabs might set the queued time any time of day
    # so we need to check to midnight, one day before the verification was created
    # and to midnight of tomorrow
    before = verification.created - datetime.timedelta(days=1)
    start_date = datetime.datetime(
        year=before.year,
        month=before.month,
        day=before.day,
    )
    end_date = datetime.datetime.now() + datetime.timedelta(days=1)
    date_format = '%Y-%m-%d'

    params = {
        'toEmailAddress': email,
        'startDate': start_date.strftime(date_format),
        'endDate': end_date.strftime(date_format),
        'pageNumber': 0,
        'pageSize': page_size,
        'sortField': 'queuedTime',
        'sortDirection': 'dsc',
    }

    is_first_page = True

    while current_count < total or is_first_page:
        if not is_first_page:
            params['pageNumber'] = params['pageNumber'] + 1

        url = (
            urllib.parse.urljoin(settings.SOCKET_LABS_HOST, path)
            + '?'
            + urllib.parse.urlencode(params)
        )

        headers = {
            'authorization': f'Bearer {settings.SOCKET_LABS_TOKEN}',
        }

        task_log.info(f'checking for {code_snippet} with params {params}')

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        json = response.json()

        if is_first_page:
            total = json['total']
            is_first_page = False

        data = json['data']
        current_count += len(data)

        ## TODO: check if we can set `customMessageId` to replace code snippet
        for item in data:
            if code_snippet in item['subject']:
                options = dict(SuppressedEmailVerification.STATUS_CHOICES).values()
                new_status = item['status']
                if new_status not in options:
                    raise Exception(
                        f'invalid status: {new_status} '
                        f'for {suppressed_email_verification_id}. '
                        f'expected {", ".join(options)}'
                    )

                verification.update(
                    status=SuppressedEmailVerification.STATUS_CHOICES[item['status']]
                )
                return

    raise Retry(
        f'failed to find {code_snippet} in {total} emails.'
        'retrying as email could not be queued yet'
    )
