import csv
import io
import shutil
import tempfile
import uuid
from unittest import mock

from django.conf import settings
from django.core import mail
from django.db.utils import OperationalError
from django.urls import reverse

import pytest
import responses
from celery.exceptions import Retry
from PIL import Image
from requests.exceptions import Timeout

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import SafeStorage
from olympia.users.models import (
    BannedUserContent,
    DisposableEmailDomainRestriction,
    SuppressedEmail,
    SuppressedEmailVerification,
)
from olympia.users.tasks import (
    bulk_add_disposable_email_domains,
    delete_photo,
    resize_photo,
    send_suppressed_email_confirmation,
    sync_suppressed_emails_task,
)


class TestDeletePhoto(TestCase):
    def setUp(self):
        self.user = user_factory(deleted=True)
        self.storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
        with self.storage.open(self.user.picture_path, mode='wb') as dst:
            dst.write(b'fake image\n')
        with self.storage.open(self.user.picture_path_original, mode='wb') as dst:
            dst.write(b'fake original image\n')

        patcher1 = mock.patch('olympia.users.tasks.copy_file_to_backup_storage')
        self.copy_file_to_backup_storage_mock = patcher1.start()
        self.copy_file_to_backup_storage_mock.return_value = 'picture-backup-name.png'
        self.addCleanup(patcher1.stop)

        patcher2 = mock.patch('olympia.users.tasks.backup_storage_enabled')
        self.backup_storage_enabled_mock = patcher2.start()
        self.backup_storage_enabled_mock.return_value = True
        self.addCleanup(patcher2.stop)

    def test_delete_photo(self):
        self.user.update(picture_type='image/png')
        delete_photo(self.user.pk)
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        assert self.copy_file_to_backup_storage_mock.call_count == 0

    def test_delete_photo_no_picture_type(self):
        delete_photo(self.user.pk)
        # Even if there is no picture_type, we delete the path on filesystem.
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        assert self.copy_file_to_backup_storage_mock.call_count == 0

    def test_delete_photo_banned_user_no_picture(self):
        # Pretend we have a picture type but somehow the original is already
        # gone. We can't backup it, we just don't want the task to fail.
        self.user.update(banned=self.days_ago(1), picture_type='image/png')
        self.storage.delete(self.user.picture_path_original)
        delete_photo(self.user.pk)
        # We did delete the other path though.
        assert not self.storage.exists(self.user.picture_path)
        # We didn't backup the original though, it wasn't there.
        assert self.copy_file_to_backup_storage_mock.call_count == 0

    def test_delete_photo_banned_user_no_picture_type(self):
        self.user.update(banned=self.days_ago(1))
        delete_photo(self.user.pk)
        # Even if there is no picture_type, we delete the path on filesystem.
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        # We didn't backup it though, it shouldn't have been there.
        assert self.copy_file_to_backup_storage_mock.call_count == 0

    def test_delete_photo_banned_user_no_backup_storage_enabled(self):
        self.backup_storage_enabled_mock.return_value = False
        self.user.update(banned=self.days_ago(1), picture_type='image/png')
        delete_photo(self.user.pk)
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        # We didn't backup the original, storage credentials are not set.
        assert self.copy_file_to_backup_storage_mock.call_count == 0

    def test_delete_photo_banned_user_successful_backup(self):
        self.user.update(banned=self.days_ago(1), picture_type='image/png')
        original_path = str(self.user.picture_path_original)
        delete_photo(self.user.pk)
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        assert self.copy_file_to_backup_storage_mock.call_count == 1
        assert self.copy_file_to_backup_storage_mock.call_args_list[0][0] == (
            original_path,
            'image/png',
        )
        assert BannedUserContent.objects.filter(user=self.user).count() == 1
        bac = BannedUserContent.objects.filter(user=self.user).get()
        assert bac.picture_type == 'image/png'
        assert bac.picture_backup_name == 'picture-backup-name.png'

    def test_delete_photo_banned_user_successful_backup_bannedusercontent_exists(self):
        self.user.update(banned=self.days_ago(1), picture_type='image/png')
        BannedUserContent.objects.create(user=self.user)
        original_path = str(self.user.picture_path_original)
        delete_photo(self.user.pk)
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        assert self.copy_file_to_backup_storage_mock.call_count == 1
        assert self.copy_file_to_backup_storage_mock.call_args_list[0][0] == (
            original_path,
            'image/png',
        )
        assert BannedUserContent.objects.filter(user=self.user).count() == 1
        bac = BannedUserContent.objects.filter(user=self.user).get()
        assert bac.picture_type == 'image/png'
        assert bac.picture_backup_name == 'picture-backup-name.png'

    def test_delete_photo_banned_kwarg_successful_backup_bannedusercontent_exists(self):
        # User hasn't been banned yet but we are passing the banned kwarg to
        # delete_photo to bypass the check.
        self.user.update(picture_type='image/png')
        BannedUserContent.objects.create(user=self.user)
        original_path = str(self.user.picture_path_original)
        delete_photo(self.user.pk, banned=self.days_ago(42))
        assert not self.storage.exists(self.user.picture_path)
        assert not self.storage.exists(self.user.picture_path_original)
        assert self.copy_file_to_backup_storage_mock.call_count == 1
        assert self.copy_file_to_backup_storage_mock.call_args_list[0][0] == (
            original_path,
            'image/png',
        )
        assert BannedUserContent.objects.filter(user=self.user).count() == 1
        bac = BannedUserContent.objects.filter(user=self.user).get()
        assert bac.picture_type == 'image/png'
        assert bac.picture_backup_name == 'picture-backup-name.png'

    def test_delete_photo_not_banned_no_backup(self):
        self.user.update(picture_type='image/png')
        delete_photo(self.user.pk)
        assert not self.storage.exists(self.user.picture_path)
        assert self.copy_file_to_backup_storage_mock.call_count == 0


def test_resize_photo():
    somepic = get_image_path('sunbird-small.png')

    src = tempfile.NamedTemporaryFile(
        mode='r+b', suffix='.png', delete=False, dir=settings.TMP_PATH
    )
    dest = tempfile.NamedTemporaryFile(mode='r+b', suffix='.png', dir=settings.TMP_PATH)

    shutil.copyfile(somepic, src.name)

    src_image = Image.open(src.name)
    assert src_image.size == (64, 64)
    resize_photo(src.name, dest.name)

    # Image is smaller than 200x200 so it should stay the same.
    dest_image = Image.open(dest.name)
    assert dest_image.size == (64, 64)


def test_resize_photo_poorly():
    """If we attempt to set the src/dst, we do nothing."""
    somepic = get_image_path('mozilla.png')
    src = tempfile.NamedTemporaryFile(
        mode='r+b', suffix='.png', delete=False, dir=settings.TMP_PATH
    )
    shutil.copyfile(somepic, src.name)
    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)

    resize_photo(src.name, src.name)

    # assert nothing happened
    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)


def list_to_csv(data):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Zero', 'One', 'Two', 'Email'])

    for item in data:
        row = ['0', '1', '2', item if item is not None else '']
        writer.writerow(row)
    return output.getvalue()


static_id = uuid.uuid4()


class TestSuppressedEmail(TestCase):
    def test_fails_missing_settings(self):
        for setting in (
            'SOCKET_LABS_TOKEN',
            'SOCKET_LABS_HOST',
            'SOCKET_LABS_SERVER_ID',
        ):
            with pytest.raises(Exception) as exc:
                setattr(settings, setting, None)
                sync_suppressed_emails_task.s().apply(throw=True)
                assert exc.match('SOCKET_LABS_TOKEN is not defined')

    def test_retry_if_api_returns_bad_response(self):
        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            status=500,
        )

        task = sync_suppressed_emails_task.s()

        with pytest.raises(Retry):
            task.apply(throw=True)

    def test_retry_if_api_returns_timeout(self):
        def timeout_callback(request):
            raise Timeout()

        responses.add_callback(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            callback=timeout_callback,
        )

        task = sync_suppressed_emails_task.s()

        with pytest.raises(Retry):
            task.apply(throw=True)

    def test_empty_csv(self):
        csv = list_to_csv([])

        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            body=csv,
            status=200,
        )

        sync_suppressed_emails_task()

        assert SuppressedEmail.objects.count() == 0

    def test_existing_email(self):
        user = user_factory()

        csv = list_to_csv([user.email])

        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            body=csv,
            status=200,
        )

        SuppressedEmail.objects.create(email=user.email)

        sync_suppressed_emails_task()

        email_block = SuppressedEmail.objects.get(email=user.email)

        assert email_block.email == user.email
        assert SuppressedEmail.objects.count() == 1

    def test_unique_email(self):
        user = user_factory()

        csv = list_to_csv([user.email])

        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            body=csv,
            status=200,
        )

        sync_suppressed_emails_task()

        email_block = SuppressedEmail.objects.get(email=user.email)

        assert email_block.email == user.email
        assert SuppressedEmail.objects.count() == 1


class TestSendSuppressedEmailConfirmation(TestCase):
    def setUp(self):
        self.user_profile = user_factory()

    def test_fails_missing_settings(self):
        for setting in (
            'SOCKET_LABS_TOKEN',
            'SOCKET_LABS_HOST',
            'SOCKET_LABS_SERVER_ID',
        ):
            with pytest.raises(Exception) as exc:
                setattr(settings, setting, None)
                send_suppressed_email_confirmation.apply(1)
                assert exc.match('SOCKET_LABS_TOKEN is not defined')

    def test_invalid_suppressed_email(self):
        assert SuppressedEmailVerification.objects.all().count() == 0
        invalid_id = 1

        with pytest.raises(Exception, match=f'invalid id: {invalid_id}'):
            send_suppressed_email_confirmation.apply([invalid_id])

    def test_socket_labs_returns_404(self):
        verification = SuppressedEmailVerification.objects.create(
            suppressed_email=SuppressedEmail.objects.create(
                email=self.user_profile.email
            )
        )

        responses.add(
            responses.DELETE,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'suppressions/remove?emailAddress={verification.suppressed_email.email}'
            ),
            status=404,
        )

        try:
            send_suppressed_email_confirmation.apply([verification.id])
        except Exception as err:
            pytest.fail('Unexpected exception: {0}'.format(err))

    def test_socket_labs_returns_5xx(self):
        verification = SuppressedEmailVerification.objects.create(
            suppressed_email=SuppressedEmail.objects.create(
                email=self.user_profile.email
            )
        )

        responses.add(
            responses.DELETE,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'suppressions/remove?emailAddress={verification.suppressed_email.email}'
            ),
            status=500,
        )

        with pytest.raises(Retry):
            send_suppressed_email_confirmation.apply([verification.id])

    def test_email_sent(self):
        verification = SuppressedEmailVerification.objects.create(
            suppressed_email=SuppressedEmail.objects.create(
                email=self.user_profile.email
            )
        )
        responses.add(
            responses.DELETE,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'suppressions/remove?emailAddress={verification.suppressed_email.email}'
            ),
            status=201,
        )

        send_suppressed_email_confirmation.apply([verification.id])

        assert len(mail.outbox) == 1

        expected_confirmation_link = absolutify(
            reverse('devhub.email_verification')
            + '?code='
            + str(verification.confirmation_code)
        )
        assert expected_confirmation_link in mail.outbox[0].body
        assert str(verification.confirmation_code)[-5:] in mail.outbox[0].subject

    def test_retry_existing_verification(
        self,
    ):
        verification = SuppressedEmailVerification.objects.create(
            suppressed_email=SuppressedEmail.objects.create(
                email=self.user_profile.email
            ),
            status=SuppressedEmailVerification.STATUS_CHOICES.FAILED,
        )

        responses.add(
            responses.DELETE,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'suppressions/remove?emailAddress={verification.suppressed_email.email}'
            ),
            status=201,
        )

        assert verification.status == SuppressedEmailVerification.STATUS_CHOICES.FAILED
        send_suppressed_email_confirmation.apply([verification.id])
        assert (
            verification.reload().status
            == SuppressedEmailVerification.STATUS_CHOICES.PENDING
        )


class TestBulkAddDisposableEmailDomains(TestCase):
    def setUp(self):
        self.user_profile = user_factory()
        self.entries = [
            (f'test-{i}-{j}.com', f'provider-{i}')
            for i in range(10)
            for j in range(100)
        ]
        # Ensure that the task runs with 2 batches by default
        self.batch_size = len(self.entries) // 2

    def test_bulk_add_disposable_email_domains_success(self):
        assert DisposableEmailDomainRestriction.objects.count() == 0

        result = bulk_add_disposable_email_domains.apply(
            args=[self.entries, self.batch_size]
        )

        assert result.status == 'SUCCESS'
        assert DisposableEmailDomainRestriction.objects.count() == len(self.entries)

    def test_bulk_add_disposable_email_domains_skips_duplicate_entries(self):
        [domain, provider] = self.entries[0]
        DisposableEmailDomainRestriction.objects.create(
            domain=domain, reason=f'Disposable email domain of {provider}'
        )
        assert DisposableEmailDomainRestriction.objects.count() == 1

        result = bulk_add_disposable_email_domains.apply(
            args=[self.entries, self.batch_size]
        )

        assert result.status == 'SUCCESS'
        assert DisposableEmailDomainRestriction.objects.count() == len(self.entries)

    def test_zero_batch_size_raises_error(self):
        with pytest.raises(ValueError):
            bulk_add_disposable_email_domains.apply(args=[self.entries, 0])

    def test_retries_on_db_timeout(self):
        def always_raise_operational_error(*args, **kwargs):
            raise OperationalError()

        with mock.patch(
            'olympia.users.tasks.DisposableEmailDomainRestriction.objects.bulk_create',
            side_effect=always_raise_operational_error,
        ):
            with pytest.raises(Retry):
                bulk_add_disposable_email_domains.apply(
                    args=[self.entries, self.batch_size]
                ).get()
