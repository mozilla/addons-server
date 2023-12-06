import csv
import io
import shutil
import tempfile
import uuid
from unittest import mock

from django.conf import settings

import pytest
import responses
from celery.exceptions import Retry
from PIL import Image
from requests.exceptions import Timeout

from olympia.amo.tests import TestCase, user_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import SafeStorage
from olympia.users.models import BannedUserContent, EmailBlock
from olympia.users.tasks import delete_photo, resize_photo, sync_blocked_emails


pytestmark = pytest.mark.django_db


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


class TestEmailBlock(TestCase):
    def test_retry_if_api_returns_bad_response(self):
        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}/servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            status=500,
        )

        task = sync_blocked_emails.s()

        with pytest.raises(Retry):
            task.apply(throw=True)

    def test_retry_if_api_returns_timeout(self):
        def timeout_callback(request):
            raise Timeout()

        responses.add_callback(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}/servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            callback=timeout_callback,
        )

        task = sync_blocked_emails.s()

        with pytest.raises(Retry):
            task.apply(throw=True)

    def test_empty_csv(self):
        csv = list_to_csv([])

        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}/servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            body=csv,
            status=200,
        )

        sync_blocked_emails()

        assert EmailBlock.objects.count() == 0

    def test_existing_email(self):
        user = user_factory()

        csv = list_to_csv([user.email])

        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}/servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            body=csv,
            status=200,
        )

        EmailBlock.objects.create(email=user.email)

        sync_blocked_emails()

        email_block = EmailBlock.objects.get(email=user.email)

        assert email_block.email == user.email
        assert EmailBlock.objects.count() == 1

    def test_unique_email(self):
        user = user_factory()

        csv = list_to_csv([user.email])

        responses.add(
            responses.GET,
            f'{settings.SOCKET_LABS_HOST}/servers/{settings.SOCKET_LABS_SERVER_ID}/suppressions/download?sortField=suppressionLastUpdate&sortDirection=dsc',
            body=csv,
            status=200,
        )

        sync_blocked_emails()

        email_block = EmailBlock.objects.get(email=user.email)

        assert email_block.email == user.email
        assert EmailBlock.objects.count() == 1
