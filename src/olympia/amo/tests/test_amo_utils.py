import os
import tempfile
from unittest import mock

from django.conf import settings
from django.core.validators import ValidationError

import pytest

from olympia.amo.tests import TestCase, get_temp_filename
from olympia.amo.utils import (
    SafeStorage,
    escape_all,
    find_language,
    from_string,
    no_jinja_autoescape,
    resize_image,
    rm_local_tmp_dir,
    slug_validator,
    slugify,
    to_language,
)


pytestmark = pytest.mark.django_db

u = 'Ελληνικά'


def test_slug_validator():
    assert slug_validator(u.lower()) is None
    assert slug_validator('-'.join([u.lower(), u.lower()])) is None
    pytest.raises(ValidationError, slug_validator, '234.add')
    pytest.raises(ValidationError, slug_validator, 'a a a')
    pytest.raises(ValidationError, slug_validator, 'tags/')


@pytest.mark.parametrize(
    'test_input,expected',
    [
        ('xx x  - "#$@ x', 'xx-x-x'),
        ('Bän...g (bang)', 'bäng-bang'),
        (u, u.lower()),
        ('-'.join([u, u]), '-'.join([u, u]).lower()),
        (' - '.join([u, u]), '-'.join([u, u]).lower()),
        ('    a ', 'a'),
        ('tags/', 'tags'),
        ('holy_wars', 'holy_wars'),
        # I don't really care what slugify returns.  Just don't crash.
        ('x荿', 'x\u837f'),
        ('ϧ΃蒬蓣', '\u03e7\u84ac\u84e3'),
        ('¿x', 'x'),
    ],
)
def test_slugify(test_input, expected):
    assert slugify(test_input) == expected
    slug_validator(slugify(test_input))


def test_resize_image():
    # src and dst shouldn't be the same.
    pytest.raises(Exception, resize_image, 't', 't', 'z')


def test_resize_image_from_svg():
    src_folder = os.path.join(
        settings.ROOT, 'src', 'olympia', 'versions', 'tests', 'static_themes'
    )
    src = os.path.join(src_folder, 'weta_theme_amo.svg')
    expected = os.path.join(src_folder, 'weta_theme_amo.jpg')
    tmp_file_name = get_temp_filename()
    try:
        resize_image(src, tmp_file_name, (720, 92), format='jpg', quality=35)
        with open(tmp_file_name, 'rb') as dfh:
            with open(expected, 'rb') as efh:
                dd = dfh.read()
                ee = efh.read()
                assert len(dd) == len(ee) and dd == ee
    finally:
        if os.path.exists(tmp_file_name):
            os.remove(tmp_file_name)


@mock.patch('olympia.amo.utils.SafeStorage.base_location', '/')
def test_resize_transparency():
    src = os.path.join(
        settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'images', 'transparent.png'
    )
    dest = tempfile.mkstemp(dir=settings.TMP_PATH)[1]
    expected = src.replace('.png', '-expected.png')
    try:
        resize_image(src, dest, (32, 32))
        with open(dest, 'rb') as dfh:
            with open(expected, 'rb') as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


@mock.patch('olympia.amo.utils.SafeStorage.base_location', '/')
def test_resize_transparency_for_P_mode_bug_1181221():
    # We had a monkeypatch that was added in
    # https://github.com/jbalogh/zamboni/commit/10340af6d1a64a16f4b9cade9faa69976b5b6da5  # noqa
    # which caused the issue in bug 1181221. Since then we upgraded Pillow, and
    # we don't need it anymore. We thus don't have this issue anymore.
    src = os.path.join(
        settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'images', 'icon64.png'
    )
    dest = tempfile.mkstemp(dir=settings.TMP_PATH)[1]
    expected = src.replace('.png', '-expected.png')
    try:
        resize_image(src, dest, (32, 32))
        with open(dest, 'rb') as dfh:
            with open(expected, 'rb') as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


@mock.patch('olympia.amo.utils.SafeStorage.base_location', '/')
def test_resize_transparency_to_jpeg_has_white_background():
    src = os.path.join(
        settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'images', 'transparent.png'
    )
    dest = tempfile.mkstemp(dir=settings.TMP_PATH)[1]
    expected = src.replace('.png', '-expected.jpg')
    try:
        resize_image(src, dest, (32, 32), format='jpg')
        with open(dest, 'rb') as dfh:
            with open(expected, 'rb') as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


@mock.patch('olympia.amo.utils.SafeStorage.base_location', '/')
def test_resize_small_png_rgb():
    src = os.path.join(
        settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'images', 'small_rgb.png'
    )
    dest = tempfile.mkstemp(dir=settings.TMP_PATH)[1]
    expected = src.replace('.png', '-expected.jpg')
    try:
        resize_image(src, dest, (533, 400), format='jpg')
        with open(dest, 'rb') as dfh:
            with open(expected, 'rb') as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


@pytest.mark.parametrize(
    'test_input,expected',
    [
        ('en-us', 'en-US'),
        ('en_US', 'en-US'),
        ('en_us', 'en-US'),
        ('FR', 'fr'),
        ('el', 'el'),
        # see https://github.com/mozilla/addons-server/issues/3375
        ('x_zh_cn', 'x-ZH-CN'),
        ('sr_Cyrl_BA', 'sr-CYRL-BA'),
        ('zh_Hans_CN', 'zh-HANS-CN'),
    ],
)
def test_to_language(test_input, expected):
    assert to_language(test_input) == expected


@pytest.mark.parametrize(
    'test_input,expected',
    [
        ('en-us', 'en-US'),
        ('en_US', 'en-US'),
        ('en', 'en-US'),
        ('FR', 'fr'),
        ('es-ES', None),  # We don't go from specific to generic.
        ('xxx', None),
        # see https://github.com/mozilla/addons-server/issues/3375
        ('x_zh-CN', None),
        ('sr_Cyrl_BA', None),
        ('zh_Hans_CN', None),
    ],
)
def test_find_language(test_input, expected):
    assert find_language(test_input) == expected


class TestSafeStorage(TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(dir=settings.TMP_PATH)
        self.stor = SafeStorage()

    def tearDown(self):
        rm_local_tmp_dir(self.tmp)
        super().tearDown()

    def test_read_write(self):
        fn = os.path.join(self.tmp, 'somefile.txt')
        with self.stor.open(fn, 'w') as fd:
            fd.write('stuff')
        with self.stor.open(fn, 'r') as fd:
            assert fd.read() == 'stuff'

    def test_non_ascii_filename(self):
        fn = os.path.join(self.tmp, 'Ivan Krsti\u0107.txt')
        with self.stor.open(fn, 'w') as fd:
            fd.write('stuff')
        with self.stor.open(fn, 'r') as fd:
            assert fd.read() == 'stuff'

    def test_non_ascii_content(self):
        fn = os.path.join(self.tmp, 'somefile.txt')
        with self.stor.open(fn, 'wb') as fd:
            fd.write('Ivan Krsti\u0107.txt'.encode())
        with self.stor.open(fn, 'rb') as fd:
            assert fd.read().decode('utf8') == 'Ivan Krsti\u0107.txt'

    def test_make_file_dirs(self):
        dp = os.path.join(self.tmp, 'path', 'to')
        self.stor.open(os.path.join(dp, 'file.txt'), 'w').close()
        assert os.path.exists(self.stor.path(dp)), 'Directory not created: %r' % dp

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
            assert fd.read() == 'stuff'

    def test_delete_empty_dir(self):
        dp = os.path.join(self.tmp, 'path')
        os.mkdir(dp)
        self.stor.delete(dp)
        assert not os.path.exists(dp)

    def test_cannot_delete_non_empty_dir(self):
        dp = os.path.join(self.tmp, 'path')
        with self.stor.open(os.path.join(dp, 'file.txt'), 'w') as fp:
            fp.write('stuff')
        self.assertRaises(OSError, self.stor.delete, dp)

    def test_delete_file(self):
        dp = os.path.join(self.tmp, 'path')
        fn = os.path.join(dp, 'file.txt')
        with self.stor.open(fn, 'w') as fp:
            fp.write('stuff')
        self.stor.delete(fn)
        assert not os.path.exists(fn)
        assert os.path.exists(dp)


@pytest.mark.parametrize(
    'test_input,expected',
    [
        (
            '<script>alert("BALL SO HARD")</script>',
            '&lt;script&gt;alert("BALL SO HARD")&lt;/script&gt;',
        ),
        ('Bän...g (bang)', 'Bän...g (bang)'),
        (u, u),
        ('-'.join([u, u]), '-'.join([u, u])),
        (' - '.join([u, u]), ' - '.join([u, u])),
        ('x荿', 'x\u837f'),
        ('ϧ΃蒬蓣', '\u03e7\u0383\u84ac\u84e3'),
        ('¿x', '¿x'),
    ],
)
def test_escape_all(test_input, expected):
    assert escape_all(test_input) == expected


@mock.patch('olympia.amo.templatetags.jinja_helpers.urlresolvers.get_outgoing_url')
@mock.patch('bleach.callbacks.nofollow', lambda attrs, new: attrs)
def test_escape_all_linkify_only_full(mock_get_outgoing_url):
    mock_get_outgoing_url.return_value = 'https://outgoing.firefox.com'

    assert escape_all('http://firefox.com') == (
        '<a href="https://outgoing.firefox.com">http://firefox.com</a>'
    )

    assert escape_all('firefox.com') == (
        '<a href="https://outgoing.firefox.com">firefox.com</a>'
    )


def test_no_jinja_autoescape():
    val = 'some double quote: " and a <'
    tpl = '{{ val }}'
    ctx = {'val': val}
    template = from_string(tpl)
    assert template.render(ctx) == 'some double quote: &#34; and a &lt;'
    with no_jinja_autoescape():
        template = from_string(tpl)
        assert template.render(ctx) == 'some double quote: " and a <'
