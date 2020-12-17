import collections
import datetime
import os.path
import tempfile

from django.conf import settings
from django.utils.functional import cached_property
from django.utils.http import quote_etag

import freezegun
from unittest import mock
import pytest

from babel import Locale

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.utils import (
    HttpResponseXSendFile,
    attach_trans_dict,
    extract_colors_from_image,
    get_locale_from_lang,
    pngcrush_image,
    utc_millesecs_from_epoch,
    walkfiles,
)


pytestmark = pytest.mark.django_db

IMAGE_FILESIZE_MAX = 200 * 1024


class TestAttachTransDict(TestCase):
    """
    Tests for attach_trans_dict. For convenience, we re-use Addon model instead
    of mocking one from scratch and we rely on internal Translation unicode
    implementation, because mocking django models and fields is just painful.
    """

    def test_basic(self):
        addon = addon_factory(
            name='Name',
            description='Description <script>alert(42)</script>!',
            eula='',
            summary='Summary',
            homepage='http://home.pa.ge',
            developer_comments='Developer Comments',
            support_email='sup@example.com',
            support_url='http://su.pport.url',
        )
        addon.save()

        # Quick sanity checks: is description properly escaped? The underlying
        # implementation should leave localized_string un-escaped but never use
        # it for __str__. We depend on this behaviour later in the test.
        assert '<script>' in addon.description.localized_string
        assert '<script>' not in addon.description.localized_string_clean
        assert '<script>' not in str(addon.description)

        # Attach trans dict.
        attach_trans_dict(Addon, [addon])
        assert isinstance(addon.translations, collections.defaultdict)
        translations = dict(addon.translations)

        # addon.translations is a defaultdict.
        assert addon.translations['whatever'] == []

        # No-translated fields should be absent.
        assert addon.privacy_policy_id is None
        assert None not in translations

        # Build expected translations dict.
        expected_translations = {
            addon.eula_id: [('en-us', str(addon.eula))],
            addon.description_id: [('en-us', str(addon.description))],
            addon.developer_comments_id: [('en-us', str(addon.developer_comments))],
            addon.summary_id: [('en-us', str(addon.summary))],
            addon.homepage_id: [('en-us', str(addon.homepage))],
            addon.name_id: [('en-us', str(addon.name))],
            addon.support_email_id: [('en-us', str(addon.support_email))],
            addon.support_url_id: [('en-us', str(addon.support_url))],
        }
        assert translations == expected_translations

    def test_multiple_objects_with_multiple_translations(self):
        addon = addon_factory()
        addon.description = {'fr': 'French Description', 'en-us': 'English Description'}
        addon.save()
        addon2 = addon_factory(description='English 2 Description')
        addon2.name = {
            'fr': 'French 2 Name',
            'en-us': 'English 2 Name',
            'es': 'Spanish 2 Name',
        }
        addon2.save()
        attach_trans_dict(Addon, [addon, addon2, None])
        assert set(addon.translations[addon.description_id]) == (
            set([('en-us', 'English Description'), ('fr', 'French Description')])
        )
        assert set(addon2.translations[addon2.name_id]) == (
            set(
                [
                    ('en-us', 'English 2 Name'),
                    ('es', 'Spanish 2 Name'),
                    ('fr', 'French 2 Name'),
                ]
            )
        )


def test_has_links():
    html = 'a text <strong>without</strong> links'
    assert not amo.utils.has_links(html)

    html = 'a <a href="http://example.com">link</a> with markup'
    assert amo.utils.has_links(html)

    html = 'a http://example.com text link'
    assert amo.utils.has_links(html)

    html = 'a badly markuped <a href="http://example.com">link'
    assert amo.utils.has_links(html)


def test_walkfiles():
    basedir = tempfile.mkdtemp(dir=settings.TMP_PATH)
    subdir = tempfile.mkdtemp(dir=basedir)
    file1, file1path = tempfile.mkstemp(dir=basedir, suffix='_foo')
    file2, file2path = tempfile.mkstemp(dir=subdir, suffix='_foo')
    file3, file3path = tempfile.mkstemp(dir=subdir, suffix='_bar')

    # Only files ending with _foo.
    assert list(walkfiles(basedir, suffix='_foo')) == [file1path, file2path]
    # All files.
    all_files = list(walkfiles(basedir))
    assert len(all_files) == 3
    assert set(all_files) == set([file1path, file2path, file3path])


def test_cached_property():
    callme = mock.Mock()

    class Foo(object):
        @cached_property
        def bar(self):
            callme()
            return 'value'

    foo = Foo()
    # Call twice...
    assert foo.bar == 'value'
    assert foo.bar == 'value'

    # Check that callme() was called only once.
    assert callme.call_count == 1


def test_set_writable_cached_property():
    callme = mock.Mock()

    class Foo(object):
        @cached_property
        def bar(self):
            callme()
            return 'original value'

    foo = Foo()
    foo.bar = 'new value'
    assert foo.bar == 'new value'

    # Check that callme() was never called, since we overwrote the prop value.
    assert callme.call_count == 0

    del foo.bar
    assert foo.bar == 'original value'
    assert callme.call_count == 1


@pytest.mark.parametrize('lang', settings.AMO_LANGUAGES)
def test_get_locale_from_lang(lang):
    """Make sure all languages in settings.AMO_LANGUAGES can be resolved."""
    locale = get_locale_from_lang(lang)

    ignored_languages = ('cak',)
    long_languages = ('ast', 'dsb', 'hsb', 'kab')
    expected_language = (
        lang[:3]
        if lang in long_languages
        else (lang[:2] if lang not in ignored_languages else 'en')
    )

    assert isinstance(locale, Locale)
    assert locale.language == expected_language

    separator = '-' if '-' in lang else '_' if '_' in lang else None

    if separator:
        territory = lang.split(separator)[1]
        assert locale.territory == territory


@pytest.mark.parametrize('lang', settings.LANGUAGES_BIDI)
def test_bidi_language_in_amo_languages(lang):
    """Make sure all bidi marked locales are in AMO_LANGUAGES too."""
    assert lang in settings.AMO_LANGUAGES


@mock.patch('olympia.amo.utils.subprocess')
def test_pngcrush_image(subprocess_mock):
    subprocess_mock.Popen.return_value.communicate.return_value = ('', '')
    subprocess_mock.Popen.return_value.returncode = 0  # success
    assert pngcrush_image('/tmp/some_file.png')
    assert subprocess_mock.Popen.call_count == 1
    assert subprocess_mock.Popen.call_args_list[0][0][0] == [
        settings.PNGCRUSH_BIN,
        '-q',
        '-reduce',
        '-ow',
        '/tmp/some_file.png',
        '/tmp/some_file.crush.png',
    ]
    assert subprocess_mock.Popen.call_args_list[0][1] == {
        'stdout': subprocess_mock.PIPE,
        'stderr': subprocess_mock.PIPE,
    }

    # Make sure that exceptions for this are silent.
    subprocess_mock.Popen.side_effect = Exception
    assert not pngcrush_image('/tmp/some_other_file.png')


def test_utc_millesecs_from_epoch():

    with freezegun.freeze_time('2018-11-18 06:05:04.030201'):
        timestamp = utc_millesecs_from_epoch()
    assert timestamp == 1542521104030

    future_now = datetime.datetime(2018, 11, 20, 4, 8, 15, 162342)
    timestamp = utc_millesecs_from_epoch(future_now)
    assert timestamp == 1542686895162

    new_timestamp = utc_millesecs_from_epoch(
        future_now + datetime.timedelta(milliseconds=42)
    )
    assert new_timestamp == timestamp + 42


def test_extract_colors_from_image():
    path = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/weta.png'
    )
    expected = [
        {'h': 45, 'l': 158, 'ratio': 0.40547158773994313, 's': 34},
        {'h': 44, 'l': 94, 'ratio': 0.2812929380875291, 's': 28},
        {'h': 68, 'l': 99, 'ratio': 0.13200103391513734, 's': 19},
        {'h': 43, 'l': 177, 'ratio': 0.06251105336906689, 's': 93},
        {'h': 47, 'l': 115, 'ratio': 0.05938209966397758, 's': 60},
        {'h': 40, 'l': 201, 'ratio': 0.05934128722434598, 's': 83},
    ]
    assert extract_colors_from_image(path) == expected


class TestHttpResponseXSendFile(TestCase):
    def test_normalizes_path(self):
        path = '/some/../path/'
        response = HttpResponseXSendFile(request=None, path=path)
        assert response[settings.XSENDFILE_HEADER] == os.path.normpath(path)
        assert not response.has_header('Content-Disposition')

    def test_adds_etag_header(self):
        etag = '123'
        response = HttpResponseXSendFile(request=None, path='/', etag=etag)
        assert response.has_header('ETag')
        assert response['ETag'] == quote_etag(etag)

    def test_adds_content_disposition_header(self):
        response = HttpResponseXSendFile(request=None, path='/', attachment=True)
        assert response.has_header('Content-Disposition')
        assert response['Content-Disposition'] == 'attachment'


def test_images_are_small():
    """A test that will fail if we accidentally include a large image."""
    large_images = []
    img_path = os.path.join(settings.ROOT, 'static', 'img')
    for root, dirs, files in os.walk(img_path):
        large_images += [
            os.path.join(root, name)
            for name in files
            if os.path.getsize(os.path.join(root, name)) > IMAGE_FILESIZE_MAX
        ]
    assert not large_images
