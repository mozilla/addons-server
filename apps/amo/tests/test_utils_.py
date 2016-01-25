import collections
import tempfile

import pytest
from nose.tools import ok_


import amo
import amo.tests
from amo.utils import attach_trans_dict, translations_for_field, walkfiles
from addons.models import Addon
from versions.models import Version


pytestmark = pytest.mark.django_db


class TestAttachTransDict(amo.tests.TestCase):
    """
    Tests for attach_trans_dict. For convenience, we re-use Addon model instead
    of mocking one from scratch and we rely on internal Translation unicode
    implementation, because mocking django models and fields is just painful.
    """

    def test_basic(self):
        addon = amo.tests.addon_factory(
            name='Name', description='Description <script>alert(42)</script>!',
            eula='', summary='Summary', homepage='http://home.pa.ge',
            developer_comments='Developer Comments', privacy_policy='Policy',
            support_email='sup@example.com', support_url='http://su.pport.url')
        addon.save()

        # Quick sanity checks: is description properly escaped? The underlying
        # implementation should leave localized_string un-escaped but never use
        # it for __unicode__. We depend on this behaviour later in the test.
        ok_('<script>' in addon.description.localized_string)
        ok_('<script>' not in addon.description.localized_string_clean)
        ok_('<script>' not in unicode(addon.description))

        # Attach trans dict.
        attach_trans_dict(Addon, [addon])
        ok_(isinstance(addon.translations, collections.defaultdict))
        translations = dict(addon.translations)
        assert addon.translations['whatever'] == []
        assert addon.thankyou_note_id is None
        ok_(None not in translations)

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
        addon = amo.tests.addon_factory()
        addon.description = {
            'fr': 'French Description',
            'en-us': 'English Description'
        }
        addon.save()
        addon2 = amo.tests.addon_factory(description='English 2 Description')
        addon2.name = {
            'fr': 'French 2 Name',
            'en-us': 'English 2 Name',
            'es': 'Spanish 2 Name'
        }
        addon2.save()
        attach_trans_dict(Addon, [addon, addon2])
        assert set(addon.translations[addon.description_id]) == set([('en-us', 'English Description'), ('fr', 'French Description')])
        assert set(addon2.translations[addon2.name_id]) == set([('en-us', 'English 2 Name'), ('es', 'Spanish 2 Name'), ('fr', 'French 2 Name')])

    def test_translations_for_field(self):
        version = Version.objects.create(addon=Addon.objects.create())
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
    assert list(walkfiles(basedir, suffix='_foo')) == [file1path, file2path]
    # All files.
    all_files = list(walkfiles(basedir))
    assert len(all_files) == 3
    assert set(all_files) == set([file1path, file2path, file3path])
