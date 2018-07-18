import os
import shutil
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage as storage

import pytest

from PIL import Image

from olympia.amo.tests.test_helpers import get_image_path
from olympia.users.tasks import delete_photo, resize_photo


pytestmark = pytest.mark.django_db


def test_delete_photo():
    dst_path = tempfile.mktemp(suffix='.png', dir=settings.TMP_PATH)
    dst = storage.open(dst_path, mode='wb')
    with dst:
        dst.write('test data\n')
    path = os.path.dirname(dst_path)
    settings.USERPICS_PATH = path
    delete_photo(dst_path)

    assert not storage.exists(dst_path)


def test_resize_photo():
    somepic = get_image_path('sunbird-small.png')

    src = tempfile.NamedTemporaryFile(
        mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH
    )
    dest = tempfile.NamedTemporaryFile(
        mode='r+w+b', suffix=".png", dir=settings.TMP_PATH
    )

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
        mode='r+w+b', suffix=".png", delete=False, dir=settings.TMP_PATH
    )
    shutil.copyfile(somepic, src.name)
    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)

    resize_photo(src.name, src.name)

    # assert nothing happened
    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)
