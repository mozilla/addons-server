import collections
import tempfile

import mock
import pytest
from babel import Locale
from django.conf import settings
from django.utils.functional import cached_property

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.utils import (
    attach_trans_dict, translations_for_field, walkfiles,
    get_locale_from_lang)
from olympia.addons.models import Addon
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


class TestAttachTransDict(TestCase):
    """
    Tests for attach_trans_dict. For convenience, we re-use Addon model instead
    of mocking one from scratch and we rely on internal Translation unicode
    implementation, because mocking django models and fields is just painful.
    """

    def test_basic(self):
        addon = addon_factory(
            name='Name', description='Description <script>alert(42)</script>!',
            eula='', summary='Summary', homepage='http://home.pa.ge',
            developer_comments='Developer Comments', privacy_policy='Policy',
            support_email='sup@example.com', support_url='http://su.pport.url')
        addon.save()

        # Quick sanity checks: is description properly escaped? The underlying
        # implementation should leave localized_string un-escaped but never use
        # it for __unicode__. We depend on this behaviour later in the test.
        assert '<script>' in addon.description.localized_string
        assert '<script>' not in addon.description.localized_string_clean
        assert '<script>' not in unicode(addon.description)

        # Attach trans dict.
        attach_trans_dict(Addon, [addon])
        assert isinstance(addon.translations, collections.defaultdict)
        translations = dict(addon.translations)

        # addon.translations is a defaultdict.
        assert addon.translations['whatever'] == []

        # No-translated fields should be absent.
        assert addon.thankyou_note_id is None
        assert None not in translations

        # Build expected translations dict.
        expected_translations = {
            addon.eula_id: [('en-us', unicode(addon.eula))],
            addon.privacy_policy_id:
                [('en-us', unicode(addon.privacy_policy))],
            addon.description_id: [
                ('en-us', unicode(addon.description))],
            addon.developer_comments_id:
                [('en-us', unicode(addon.developer_comments))],
            addon.summary_id: [('en-us', unicode(addon.summary))],
            addon.homepage_id: [('en-us', unicode(addon.homepage))],
            addon.name_id: [('en-us', unicode(addon.name))],
            addon.support_email_id: [('en-us', unicode(addon.support_email))],
            addon.support_url_id: [('en-us', unicode(addon.support_url))]
        }
        assert translations == expected_translations

    def test_multiple_objects_with_multiple_translations(self):
        addon = addon_factory()
        addon.description = {
            'fr': 'French Description',
            'en-us': 'English Description'
        }
        addon.save()
        addon2 = addon_factory(description='English 2 Description')
        addon2.name = {
            'fr': 'French 2 Name',
            'en-us': 'English 2 Name',
            'es': 'Spanish 2 Name'
        }
        addon2.save()
        attach_trans_dict(Addon, [addon, addon2])
        assert set(addon.translations[addon.description_id]) == (
            set([('en-us', 'English Description'),
                 ('fr', 'French Description')]))
        assert set(addon2.translations[addon2.name_id]) == (
            set([('en-us', 'English 2 Name'),
                 ('es', 'Spanish 2 Name'),
                 ('fr', 'French 2 Name')]))

    def test_translations_for_field(self):
        version = Version.objects.create(addon=Addon.objects.create())

        # No translations.
        assert translations_for_field(version.releasenotes) == {}

        # With translations.
        initial = {'en-us': 'release notes', 'fr': 'notes de version'}
        version.releasenotes = initial
        version.save()

        translations = translations_for_field(version.releasenotes)
        assert translations == initial


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
    basedir = tempfile.mkdtemp()
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

    debug_languages = ('dbg', 'dbr', 'dbl')
    expected_language = lang[:2] if lang not in debug_languages else 'en'

    assert isinstance(locale, Locale)
    assert locale.language == expected_language

    separator = '-' if '-' in lang else '_' if '_' in lang else None

    if separator:
        territory = lang.split(separator)[1]
        assert locale.territory == territory
