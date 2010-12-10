import os
import shutil
import tempfile

from django.conf import settings

from nose.tools import eq_
from PIL import Image

from devhub.tasks import resize_icon


def test_resize_icon_shrink():
    """ Image should be shrunk so that the longest side is 32px. """

    resize_size = 32
    final_size = (32, 12)

    _uploader(resize_size, final_size)


def test_resize_icon_enlarge():
    """ Image stays the same, since the new size is bigger than both sides. """

    resize_size = 100
    final_size = (82, 31)

    _uploader(resize_size, final_size)


def test_resize_icon_same():
    """ Image stays the same, since the new size is the same. """

    resize_size = 82
    final_size = (82, 31)

    _uploader(resize_size, final_size)


def test_resize_icon_list():
    """ Resize multiple images at once. """

    resize_size = [32, 82, 100]
    final_size = [(32, 12), (82, 31), (82, 31)]

    _uploader(resize_size, final_size)


def _uploader(resize_size, final_size):
    img = "%s/img/amo2009/tab-mozilla.png" % settings.MEDIA_ROOT
    original_size = (82, 31)

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)

    # resize_icon removes the original
    shutil.copyfile(img, src.name)

    src_image = Image.open(src.name)
    eq_(src_image.size, original_size)

    if isinstance(final_size, list):
        for rsize, fsize in zip(resize_size, final_size):
            dest_name = '1234'

            resize_icon(src.name, dest_name, resize_size)
            dest_image = Image.open("%s-%s.png" % (dest_name, rsize))
            eq_(dest_image.size, fsize)

            if os.path.exists(dest_image.filename):
                os.remove(dest_image.filename)
            assert not os.path.exists(dest_image.filename)
    else:
        dest = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png")
        resize_icon(src.name, dest.name, resize_size)
        dest_image = Image.open(dest.name)
        eq_(dest_image.size, final_size)

    assert not os.path.exists(src.name)
