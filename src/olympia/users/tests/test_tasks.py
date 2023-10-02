import shutil
import tempfile

from django.conf import settings
from django.test.utils import override_settings

import pytest
from PIL import Image

from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import SafeStorage
from olympia.users.models import UserProfile
from olympia.users.tasks import delete_photo, resize_photo


pytestmark = pytest.mark.django_db


def test_delete_photo():
    with tempfile.TemporaryDirectory(dir=settings.TMP_PATH) as tmp_media_path:
        with override_settings(MEDIA_ROOT=tmp_media_path):
            user = UserProfile(pk=42)
            storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
            with storage.open(user.picture_path, mode='wb') as dst:
                dst.write(b'test data\n')

            assert storage.exists(user.picture_path)

            delete_photo(user.pk)

            assert not storage.exists(user.picture_path)


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
