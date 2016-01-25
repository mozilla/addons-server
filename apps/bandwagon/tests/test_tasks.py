import os
import shutil
import tempfile

from django.conf import settings

import pytest
from PIL import Image

from amo.tests.test_helpers import get_image_path
from bandwagon.tasks import resize_icon


pytestmark = pytest.mark.django_db


def test_resize_icon():
    somepic = get_image_path('mozilla.png')

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False, dir=settings.TMP_PATH)
    dest = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                       dir=settings.TMP_PATH)

    # resize_icon removes the original
    shutil.copyfile(somepic, src.name)

    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)
    resize_icon(src.name, dest.name, locally=True)

    dest_image = Image.open(dest.name)
    assert dest_image.size == (32, 12)

    assert not os.path.exists(src.name)


def test_resize_icon_poorly():
    """If we attempt to set the src/dst, we do nothing."""
    somepic = get_image_path('mozilla.png')
    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False, dir=settings.TMP_PATH)
    shutil.copyfile(somepic, src.name)
    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)

    resize_icon(src.name, src.name, locally=True)

    # assert nothing happenned
    src_image = Image.open(src.name)
    assert src_image.size == (339, 128)
