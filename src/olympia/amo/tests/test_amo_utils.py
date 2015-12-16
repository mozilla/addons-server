# -*- coding: utf-8 -*-
import os
import tempfile

from django.conf import settings
from django.core.cache import cache
from django.core.validators import ValidationError
from django.utils import translation

import jingo
import mock
import pytest
from nose.tools import eq_, assert_raises, raises
from product_details import product_details

from olympia.amo.tests import BaseTestCase
from olympia.amo.utils import (
    cache_ns_key, escape_all, find_language,
    LocalFileStorage, no_jinja_autoescape, no_translation,
    resize_image, rm_local_tmp_dir, slugify, slug_validator,
    to_language)


pytestmark = pytest.mark.django_db

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
         (u'ϧ΃蒬蓣', u'\u03e7\u84ac\u84e3'),
         (u'¿x', u'x')]
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
        resize_image(src, dest, (32, 32), remove_src=False, locally=True)
        with open(dest) as dfh:
            with open(expected) as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


def test_resize_transparency_for_P_mode_bug_1181221():
    # We had a monkeypatch that was added in
    # https://github.com/jbalogh/zamboni/commit/10340af6d1a64a16f4b9cade9faa69976b5b6da5  # noqa
    # which caused the issue in bug 1181221. Since then we upgraded Pillow, and
    # we don't need it anymore. We thus don't have this issue anymore.
    src = os.path.join(settings.ROOT, 'apps', 'amo', 'tests',
                       'images', 'icon64.png')
    dest = tempfile.mkstemp(dir=settings.TMP_PATH)[1]
    expected = src.replace('.png', '-expected.png')
    try:
        resize_image(src, dest, (32, 32), remove_src=False, locally=True)
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


def test_find_language():
    tests = (('en-us', 'en-US'),
             ('en_US', 'en-US'),
             ('en', 'en-US'),
             ('cy', 'cy'),  # A hidden language.
             ('FR', 'fr'),
             ('es-ES', None),  # We don't go from specific to generic.
             ('xxx', None))

    def check(a, b):
        eq_(find_language(a), b)
    for a, b in tests:
        yield check, a, b


@pytest.mark.skipif(
    not product_details.last_update,
    reason="We don't want to download product_details on travis")
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
    old_lang = translation.get_language()
    try:
        translation.activate('pt-br')
        with no_translation():
            assert (translation.get_language().lower() ==
                    settings.LANGUAGE_CODE.lower())
        assert translation.get_language() == 'pt-br'
        with no_translation('es'):
            assert translation.get_language() == 'es'
        assert translation.get_language() == 'pt-br'
    finally:
        translation.activate(old_lang)


class TestLocalFileStorage(BaseTestCase):

    def setUp(self):
        super(TestLocalFileStorage, self).setUp()
        self.tmp = tempfile.mkdtemp()
        self.stor = LocalFileStorage()

    def tearDown(self):
        rm_local_tmp_dir(self.tmp)
        super(TestLocalFileStorage, self).tearDown()

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


class TestCacheNamespaces(BaseTestCase):

    def setUp(self):
        super(TestCacheNamespaces, self).setUp()
        cache.clear()
        self.namespace = 'redis-is-dead'

    @mock.patch('amo.utils.epoch')
    def test_no_preexisting_key(self, epoch_mock):
        epoch_mock.return_value = 123456
        eq_(cache_ns_key(self.namespace), '123456:ns:%s' % self.namespace)

    @mock.patch('amo.utils.epoch')
    def test_no_preexisting_key_incr(self, epoch_mock):
        epoch_mock.return_value = 123456
        eq_(cache_ns_key(self.namespace, increment=True),
            '123456:ns:%s' % self.namespace)

    @mock.patch('amo.utils.epoch')
    def test_key_incr(self, epoch_mock):
        epoch_mock.return_value = 123456
        cache_ns_key(self.namespace)  # Sets ns to 123456
        ns_key = cache_ns_key(self.namespace, increment=True)
        expected = '123457:ns:%s' % self.namespace
        eq_(ns_key, expected)
        eq_(cache_ns_key(self.namespace), expected)


def test_escape_all():
    x = '-'.join([u, u])
    y = ' - '.join([u, u])

    def check(x, y):
        eq_(escape_all(x), y)

    # All I ask: Don't crash me, bro.
    s = [
        ('<script>alert("BALL SO HARD")</script>',
         '&lt;script&gt;alert("BALL SO HARD")&lt;/script&gt;'),
        (u'Bän...g (bang)', u'Bän...g (bang)'),
        (u, u),
        (x, x),
        (y, y),
        (u'x荿', u'x\u837f'),
        (u'ϧ΃蒬蓣', u'\u03e7\u0383\u84ac\u84e3'),
        (u'¿x', u'¿x'),
    ]
    for val, expected in s:
        yield check, val, expected


@mock.patch('amo.helpers.urlresolvers.get_outgoing_url')
@mock.patch('bleach.callbacks.nofollow', lambda attrs, new: attrs)
def test_escape_all_linkify_only_full(mock_get_outgoing_url):
    mock_get_outgoing_url.return_value = 'http://outgoing.firefox.com'

    eq_(escape_all('http://firefox.com', linkify_only_full=True),
        '<a href="http://outgoing.firefox.com">http://firefox.com</a>')
    eq_(escape_all('http://firefox.com', linkify_only_full=False),
        '<a href="http://outgoing.firefox.com">http://firefox.com</a>')

    eq_(escape_all('firefox.com', linkify_only_full=True), 'firefox.com')
    eq_(escape_all('firefox.com', linkify_only_full=False),
        '<a href="http://outgoing.firefox.com">firefox.com</a>')


def test_no_jinja_autoescape():
    val = 'some double quote: " and a <'
    tpl = '{{ val }}'
    ctx = {'val': val}
    template = jingo.env.from_string(tpl)
    eq_(template.render(ctx), 'some double quote: &#34; and a &lt;')
    with no_jinja_autoescape():
        template = jingo.env.from_string(tpl)
        eq_(template.render(ctx), 'some double quote: " and a <')
