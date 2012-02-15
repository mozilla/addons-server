# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

from django.conf import settings
from django.core.validators import ValidationError
from django.utils import translation

from nose.tools import eq_, assert_raises, raises

from amo.utils import (slug_validator, slugify, resize_image, to_language,
                       no_translation, LocalFileStorage, rm_local_tmp_dir)
from product_details import product_details


u = u'Ελληνικά'


def test_slug_validator():
    eq_(slug_validator(u.lower()), None)
    eq_(slug_validator('-'.join([u.lower(), u.lower()])), None)
    assert_raises(ValidationError, slug_validator, '234.add')
    assert_raises(ValidationError, slug_validator, 'a a a')
    assert_raises(ValidationError, slug_validator, 'tags/')


def test_slugify():
    x = '-'.join([u, u])
    y = ' - '.join([u, u])

    def check(x, y):
        eq_(slugify(x), y)
        slug_validator(slugify(x))
    s = [('xx x  - "#$@ x', 'xx-x-x'),
         (u'Bän...g (bang)', u'bäng-bang'),
         (u, u.lower()),
         (x, x.lower()),
         (y, x.lower()),
         ('    a ', 'a'),
         ('tags/', 'tags'),
         ('holy_wars', 'holy_wars'),
         # I don't really care what slugify returns.  Just don't crash.
         (u'x荿', u'x\u837f'),
         (u'ϧ΃蒬蓣',  u'\u03e7\u84ac\u84e3'),
         (u'¿x', u'x'),
    ]
    for val, expected in s:
        yield check, val, expected


def test_resize_image():
    # src and dst shouldn't be the same.
    assert_raises(Exception, resize_image, 't', 't', 'z')


def test_resize_transparency():
    src = os.path.join(settings.ROOT, 'apps', 'amo', 'tests',
                       'images', 'transparent.png')
    dest = tempfile.mkstemp(dir=settings.TMP_PATH)[1]
    expected = src.replace('.png', '-expected.png')
    try:
        resize_image(src, dest, (32, 32), remove_src=False)
        with open(dest) as dfh:
            with open(expected) as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


def test_to_language():
    tests = (('en-us', 'en-US'),
             ('en_US', 'en-US'),
             ('en_us', 'en-US'),
             ('FR', 'fr'),
             ('el', 'el'))

    def check(a, b):
        eq_(to_language(a), b)
    for a, b in tests:
        yield check, a, b


def test_spotcheck():
    """Check a couple product-details files to make sure they're available."""
    languages = product_details.languages
    eq_(languages['el']['English'], 'Greek')
    eq_(languages['el']['native'], u'Ελληνικά')

    eq_(product_details.firefox_history_major_releases['1.0'], '2004-11-09')


def test_no_translation():
    """
    `no_translation` provides a context where only the default
    language is active.
    """
    lang = translation.get_language()
    translation.activate('pt-br')
    with no_translation():
        eq_(translation.get_language(),
            settings.LANGUAGE_CODE)
    eq_(translation.get_language(),
        'pt-br')
    translation.activate(lang)


class TestLocalFileStorage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.stor = LocalFileStorage()

    def tearDown(self):
        rm_local_tmp_dir(self.tmp)

    def test_read_write(self):
        fn = os.path.join(self.tmp, 'somefile.txt')
        with self.stor.open(fn, 'w') as fd:
            fd.write('stuff')
        with self.stor.open(fn, 'r') as fd:
            eq_(fd.read(), 'stuff')

    def test_non_ascii_filename(self):
        fn = os.path.join(self.tmp, u'Ivan Krsti\u0107.txt')
        with self.stor.open(fn, 'w') as fd:
            fd.write('stuff')
        with self.stor.open(fn, 'r') as fd:
            eq_(fd.read(), 'stuff')

    def test_non_ascii_content(self):
        fn = os.path.join(self.tmp, 'somefile.txt')
        with self.stor.open(fn, 'w') as fd:
            fd.write(u'Ivan Krsti\u0107.txt'.encode('utf8'))
        with self.stor.open(fn, 'r') as fd:
            eq_(fd.read().decode('utf8'), u'Ivan Krsti\u0107.txt')

    def test_make_file_dirs(self):
        dp = os.path.join(self.tmp, 'path', 'to')
        self.stor.open(os.path.join(dp, 'file.txt'), 'w').close()
        assert os.path.exists(self.stor.path(dp)), (
                                        'Directory not created: %r' % dp)

    def test_do_not_make_file_dirs_when_reading(self):
        fpath = os.path.join(self.tmp, 'file.txt')
        with open(fpath, 'w') as fp:
            fp.write('content')
        # Make sure this doesn't raise an exception.
        self.stor.open(fpath, 'r').close()

    def test_make_dirs_only_once(self):
        dp = os.path.join(self.tmp, 'path', 'to')
        with self.stor.open(os.path.join(dp, 'file.txt'), 'w') as fd:
            fd.write('stuff')
        # Make sure it doesn't try to make the dir twice
        with self.stor.open(os.path.join(dp, 'file.txt'), 'w') as fd:
            fd.write('stuff')
        with self.stor.open(os.path.join(dp, 'file.txt'), 'r') as fd:
            eq_(fd.read(), 'stuff')

    def test_delete_empty_dir(self):
        dp = os.path.join(self.tmp, 'path')
        os.mkdir(dp)
        self.stor.delete(dp)
        eq_(os.path.exists(dp), False)

    @raises(OSError)
    def test_cannot_delete_non_empty_dir(self):
        dp = os.path.join(self.tmp, 'path')
        with self.stor.open(os.path.join(dp, 'file.txt'), 'w') as fp:
            fp.write('stuff')
        self.stor.delete(dp)

    def test_delete_file(self):
        dp = os.path.join(self.tmp, 'path')
        fn = os.path.join(dp, 'file.txt')
        with self.stor.open(fn, 'w') as fp:
            fp.write('stuff')
        self.stor.delete(fn)
        eq_(os.path.exists(fn), False)
        eq_(os.path.exists(dp), True)
