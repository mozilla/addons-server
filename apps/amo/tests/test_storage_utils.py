from functools import partial
import os
import tempfile
import unittest

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage as storage

from nose.tools import eq_

from amo.storage_utils import (walk_storage, copy_stored_file,
                               move_stored_file, rm_stored_dir)
from amo.utils import rm_local_tmp_dir


def test_storage_walk():
    tmp = tempfile.mkdtemp()
    jn = partial(os.path.join, tmp)
    try:
        storage.save(jn('file1.txt'), ContentFile(''))
        storage.save(jn('one/file1.txt'), ContentFile(''))
        storage.save(jn('one/file2.txt'), ContentFile(''))
        storage.save(jn('one/two/file1.txt'), ContentFile(''))
        storage.save(jn('one/three/file1.txt'), ContentFile(''))
        storage.save(jn('four/five/file1.txt'), ContentFile(''))
        storage.save(jn(u'four/kristi\u0107/kristi\u0107.txt'),
                     ContentFile(''))

        results = list(sorted(walk_storage(tmp)))

        yield (eq_, results.pop(0), (tmp, ['four', 'one'], ['file1.txt']))
        yield (eq_, results.pop(0), (jn('four'),
                                     ['five', 'kristic\xcc\x81'], []))
        yield (eq_, results.pop(0), (jn('four/five'), [], ['file1.txt']))
        yield (eq_, results.pop(0), (jn('four/kristic\xcc\x81'), [],
                                     ['kristic\xcc\x81.txt']))
        yield (eq_, results.pop(0), (jn('one'), ['three', 'two'],
                                     ['file1.txt', 'file2.txt']))
        yield (eq_, results.pop(0), (jn('one/three'), [], ['file1.txt']))
        yield (eq_, results.pop(0), (jn('one/two'), [], ['file1.txt']))
        yield (eq_, len(results), 0)
    finally:
        rm_local_tmp_dir(tmp)


def test_rm_stored_dir():
    tmp = tempfile.mkdtemp()
    jn = partial(os.path.join, tmp)
    try:
        storage.save(jn('file1.txt'), ContentFile('<stuff>'))
        storage.save(jn('one/file1.txt'), ContentFile(''))
        storage.save(jn('one/two/file1.txt'), ContentFile('moar stuff'))
        storage.save(jn(u'one/kristi\u0107/kristi\u0107.txt'),
                     ContentFile(''))

        rm_stored_dir(jn('one'))

        yield (eq_, storage.exists(jn('one')), False)
        yield (eq_, storage.exists(jn('one/file1.txt')), False)
        yield (eq_, storage.exists(jn('one/two')), False)
        yield (eq_, storage.exists(jn('one/two/file1.txt')), False)
        yield (eq_, storage.exists(jn(u'one/kristi\u0107/kristi\u0107.txt')),
               False)
        yield (eq_, storage.exists(jn('file1.txt')), True)
    finally:
        rm_local_tmp_dir(tmp)


class TestFileOps(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        rm_local_tmp_dir(self.tmp)

    def path(self, path):
        return os.path.join(self.tmp, path)

    def contents(self, path):
        with storage.open(path, 'rb') as fp:
            return fp.read()

    def newfile(self, name, contents):
        src = self.path(name)
        storage.save(src, ContentFile(contents))
        return src

    def test_copy(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        copy_stored_file(src, dest)
        eq_(self.contents(dest), '<contents>')

    def test_move(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        move_stored_file(src, dest)
        eq_(self.contents(dest), '<contents>')
        eq_(storage.exists(src), False)

    def test_non_ascii(self):
        src = self.newfile(u'kristi\u0107.txt',
                           u'ivan kristi\u0107'.encode('utf8'))
        dest = self.path(u'somedir/kristi\u0107.txt')
        copy_stored_file(src, dest)
        eq_(self.contents(dest), 'ivan kristi\xc4\x87')

    def test_copy_chunking(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        copy_stored_file(src, dest, chunk_size=1)
        eq_(self.contents(dest), '<contents>')

    def test_move_chunking(self):
        src = self.newfile('src.txt', '<contents>')
        dest = self.path('somedir/dest.txt')
        move_stored_file(src, dest, chunk_size=1)
        eq_(self.contents(dest), '<contents>')
        eq_(storage.exists(src), False)
