import os
import tempfile

from functools import partial

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.encoding import force_str

import pytest

from olympia.amo.tests import TestCase
from olympia.amo.utils import rm_local_tmp_dir, SafeStorage


pytestmark = pytest.mark.django_db


def test_storage_walk():
    tmp = force_str(tempfile.mkdtemp(dir=settings.TMP_PATH))
    jn = partial(os.path.join, tmp)
    storage = SafeStorage(user_media='tmp')
    try:
        storage.save(jn('file1.txt'), ContentFile(''))
        storage.save(jn('one/file1.txt'), ContentFile(''))
        storage.save(jn('one/file2.txt'), ContentFile(''))
        storage.save(jn('one/two/file1.txt'), ContentFile(''))
        storage.save(jn('one/three/file1.txt'), ContentFile(''))
        storage.save(jn('four/five/file1.txt'), ContentFile(''))
        storage.save(jn('four/kristi\u2603/kristi\u2603.txt'), ContentFile(''))

        results = [
            (dir, set(subdirs), set(files))
            for dir, subdirs, files in sorted(storage.walk(tmp))
        ]

        assert results.pop(0) == (tmp, {'four', 'one'}, {'file1.txt'})
        assert results.pop(0) == (jn('four'), {'five', 'kristi\u2603'}, set())
        assert results.pop(0) == (jn('four/five'), set(), {'file1.txt'})
        assert results.pop(0) == (
            jn('four/kristi\u2603'),
            set(),
            {'kristi\u2603.txt'},
        )
        assert results.pop(0) == (
            jn('one'),
            {'three', 'two'},
            {'file1.txt', 'file2.txt'},
        )
        assert results.pop(0) == (jn('one/three'), set(), {'file1.txt'})
        assert results.pop(0) == (jn('one/two'), set(), {'file1.txt'})
        assert len(results) == 0
    finally:
        rm_local_tmp_dir(tmp)


def test_rm_stored_dir():
    tmp = tempfile.mkdtemp(dir=settings.TMP_PATH)
    jn = partial(os.path.join, tmp)
    storage = SafeStorage(user_media='tmp')
    try:
        storage.save(jn('file1.txt'), ContentFile('<stuff>'))
        storage.save(jn('one/file1.txt'), ContentFile(''))
        storage.save(jn('one/two/file1.txt'), ContentFile('moar stuff'))
        storage.save(jn('one/kristi\u0107/kristi\u0107.txt'), ContentFile(''))

        storage.rm_stored_dir(jn('one'))

        assert not storage.exists(jn('one'))
        assert not storage.exists(jn('one/file1.txt'))
        assert not storage.exists(jn('one/two'))
        assert not storage.exists(jn('one/two/file1.txt'))
        assert not storage.exists(jn('one/kristi\u0107/kristi\u0107.txt'))
        assert storage.exists(jn('file1.txt'))
    finally:
        rm_local_tmp_dir(tmp)


class TestFileOps(TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(dir=settings.TMP_PATH)
        self.storage = SafeStorage(user_media='tmp')

    def tearDown(self):
        rm_local_tmp_dir(self.tmp)
        super().tearDown()

    def path(self, path):
        return os.path.join(self.tmp, path)

    def contents(self, path):
        with self.storage.open(path, 'rb') as fp:
            return fp.read()

    def newfile(self, name, contents):
        src = self.path(name)
        self.storage.save(src, ContentFile(contents))
        return src

    def test_copy(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        self.storage.copy_stored_file(src, dest)
        assert self.contents(dest) == b'<contents>'

    def test_self_copy(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('src.txt')
        self.storage.copy_stored_file(src, dest)
        assert self.contents(dest) == b'<contents>'

    def test_move(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        self.storage.move_stored_file(src, dest)
        assert self.contents(dest) == b'<contents>'
        assert not self.storage.exists(src)

    def test_non_ascii(self):
        src = self.newfile('kristi\u0107.txt', 'ivan kristi\u0107'.encode())
        dest = self.path('somedir/kristi\u0107.txt')
        self.storage.copy_stored_file(src, dest)
        assert self.contents(dest) == b'ivan kristi\xc4\x87'

    def test_copy_chunking(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        self.storage.copy_stored_file(src, dest, chunk_size=1)
        assert self.contents(dest) == b'<contents>'

    def test_move_chunking(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        self.storage.move_stored_file(src, dest, chunk_size=1)
        assert self.contents(dest) == b'<contents>'
        assert not self.storage.exists(src)
