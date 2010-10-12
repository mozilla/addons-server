import os
import shutil
import tempfile


from django.conf import settings

from nose.tools import eq_
from PIL import Image

from users.tasks import delete_photo, resize_photo


def test_delete_photo():
    dst = tempfile.NamedTemporaryFile(mode='r+w+b', suffix='.png',
                                      delete=False)
    path = os.path.dirname(dst.name)
    settings.USERPICS_PATH = path
    delete_photo(dst.name)

    assert not os.path.exists(dst.name)


def test_resize_photo():
    somepic = "%s/img/amo2009/tab-mozilla.png" % settings.MEDIA_ROOT

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)
    dest = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png")

    # resize_photo removes the original
    shutil.copyfile(somepic, src.name)

    src_image = Image.open(src.name)
    eq_(src_image.size, (82, 31))

    resize_photo(src.name, dest.name)

    # Image is smaller than 200x200 so it should stay the same.
    dest_image = Image.open(dest.name)
    eq_(dest_image.size, (82, 31))

    assert not os.path.exists(src.name)


def test_resize_photo_poorly():
    """If we attempt to set the src/dst, we do nothing."""
    somepic = "%s/img/amo2009/tab-mozilla.png" % settings.MEDIA_ROOT
    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)
    shutil.copyfile(somepic, src.name)
    src_image = Image.open(src.name)
    eq_(src_image.size, (82, 31))

    resize_photo(src.name, src.name)

    # assert nothing happenned
    src_image = Image.open(src.name)
    eq_(src_image.size, (82, 31))
