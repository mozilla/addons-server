# -*- coding: utf-8 -*-
from django.conf import settings

import pytest


@pytest.mark.parametrize('key', (
    'NETAPP_STORAGE', 'GUARDED_ADDONS_PATH', 'MEDIA_ROOT', 'TMP_PATH',
    'MEDIA_ROOT'))
def test_base_paths_bytestring(key):
    """Make sure all relevant base paths are bytestrings.

    Filenames and filesystem paths are generally handled as byte-strings
    and we are running into various errors if they're not.

    One of many examples would be

    >>> os.path.join(u'path1', u'pæth2'.encode('utf-8'))
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
      File "/usr/lib64/python2.7/posixpath.py", line 80, in join
        path += '/' + b
    UnicodeDecodeError: 'ascii' codec can't decode byte...

    See https://github.com/mozilla/addons-server/issues/3579 for context.
    """
    assert isinstance(getattr(settings, key), str)
