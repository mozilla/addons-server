import csv
import itertools
import tempfile
import urllib.parse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.utils import InterfaceError, OperationalError
from django.urls import reverse
from django.utils.translation import gettext

import requests
from requests.exceptions import HTTPError, Timeout

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import (
    SafeStorage,
    backup_storage_enabled,
    copy_file_to_backup_storage,
    resize_image,
    send_mail_jinja,
)

from .models import (
    RESTRICTION_TYPES,
    BannedUserContent,
    DisposableEmailDomainRestriction,
    EmailUserRestriction,
    SuppressedEmail,
    SuppressedEmailVerification,
    UserProfile,
)
from .utils import assert_socket_labs_settings_defined


task_log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def restrict_banned_users(ids, **kw):
    task_log.info(
        '[1@None] Restricting banned users %d-%d [%d].',
        ids[0],
        ids[-1],
        len(ids),
    )
    users = UserProfile.objects.filter(banned__isnull=False, pk__in=ids)
    EmailUserRestriction.objects.bulk_create(
        [
            EmailUserRestriction(
                email_pattern=EmailUserRestriction.normalize_email(user.email),
                restriction_type=restriction_type,
                reason=f'Automatically added because of user {user.pk} ban (backfill)',
            )
            for user in users
            for restriction_type in [
                RESTRICTION_TYPES.ADDON_SUBMISSION,
                RESTRICTION_TYPES.RATING,
            ]
        ],
        ignore_conflicts=True,
    )


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
def sync_suppressed_emails_task(batch_size=BATCH_SIZE, **kw):
    assert_socket_labs_settings_defined()

    task_log.info('fetching suppression list from socket labs...')

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

    size_in_mb = len(response.content) / (1024 * 1024)
    task_log.info(f'Downloaded suppression list of {size_in_mb:.2f} MB.')

    with tempfile.NamedTemporaryFile(
        dir=settings.TMP_PATH, delete=not settings.DEBUG, mode='w+b'
    ) as csv_file:
        csv_file.write(response.content)
        csv_file.seek(0)

        with open(csv_file.name, 'r') as f:
            csv_suppression_list = csv.reader(f)

            next(csv_suppression_list)

            count = 0

            while True:
                batch = list(itertools.islice(csv_suppression_list, batch_size))

                if not batch:
                    break

                email_blocks = [SuppressedEmail(email=record[3]) for record in batch]
                SuppressedEmail.objects.bulk_create(email_blocks, ignore_conflicts=True)
                count += len(batch)

            task_log.info(f'synced {count:,} suppressed emails.')


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

    task_log.info('email removed from suppression')

    code_snippet = str(verification.confirmation_code)[-5:]

    verification.status = SuppressedEmailVerification.STATUS_CHOICES.PENDING

    confirmation_link = absolutify(
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


@task(
    autoretry_for=(OperationalError, InterfaceError), max_retries=5, retry_backoff=True
)
def bulk_add_disposable_email_domains(entries: list[tuple[str, str]], batch_size=1000):
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError('batch_size must be a positive integer')

    task_log.info(f'Adding {len(entries)} disposable email domains')

    records = []
    errors = []

    for entry in entries:
        [domain, provider] = entry
        record = DisposableEmailDomainRestriction(
            domain=domain,
            reason=f'Disposable email domain of {provider}',
        )

        try:
            record.full_clean()
            records.append(record)
        except ValidationError as e:
            errors.append(e)

    if not records:
        task_log.info('No valid entries provided')
        return

    processed_domains = []

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        created_objects = DisposableEmailDomainRestriction.objects.bulk_create(
            batch,
            batch_size,
            ignore_conflicts=True,
        )
        processed_domains.extend(created_objects)
        task_log.info(
            f'Successfully processed {len(created_objects)} '
            f'of {len(batch)} domains in this batch'
        )

    task_log.info(
        f'Processed {len(processed_domains)} domains: '
        f'{[obj.domain for obj in processed_domains]}'
    )
