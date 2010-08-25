import os
import tempfile

from django.conf import settings


def test_delete_photo():
    dst = tempfile.NamedTemporaryFile(mode='r+w+b', suffix='.png',
                                      delete=False)
    path = os.path.dirname(dst.name)
    settings.USERPICS_PATH = path
    from users.tasks import delete_photo
    delete_photo(dst.name)

    assert not os.path.exists(dst.name)
