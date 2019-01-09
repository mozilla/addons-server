# -*- coding: utf-8 -*-
import mimetypes
import os
import zipfile

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage

import flufl.lock
import pytest

from freezegun import freeze_time
from mock import Mock, patch

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory
from olympia.files.models import File
from olympia.files.file_viewer import DiffHelper, FileViewer
from olympia.files.utils import SafeZip, get_all_files
from olympia.versions.tasks import extract_version_to_git


def make_file(file_path):
    addon = addon_factory(
        name=u'My Addôn', slug='my-addon',
        file_kw={'filename': file_path})

    return addon.current_version.current_file


class TestFileViewer(TestCase):

    def test_files_not_extracted_by_default(self):
        # Files should be extracted by default via on-upload git-extraction
        # but the file-viewer doesn't extract anything on initialization.
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        assert not viewer.is_extracted()

    def test_files_extracted(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        viewer.extract()
        assert viewer.is_extracted()

    def test_recurse_extract(self):
        viewer = FileViewer(make_file('recurse.xpi'))
        viewer.extract()
        assert viewer.is_extracted()

    def test_recurse_contents(self):
        viewer = FileViewer(make_file('recurse.xpi'))
        viewer.extract()
        files = viewer.get_files()
        # We do not extract nested .zip or .xpi files anymore
        assert files.keys() == [
            u'recurse',
            u'recurse/chrome',
            u'recurse/chrome/test-root.txt',
            u'recurse/chrome/test.jar',
            u'recurse/notazip.jar',
            u'recurse/recurse.xpi',
            u'recurse/somejar.jar']

    def test_locked(self):
        # Lock was successfully attained
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        assert viewer.extract()

        lock = flufl.lock.Lock(os.path.join(
            settings.TMP_PATH, 'git-storage-%s.lock' % viewer.file.pk
        ))

        assert not lock.is_locked

        lock.lock()

        assert lock.is_locked

        # Not extracting, the viewer is locked, lock could not be attained
        assert not viewer.extract()

    def test_truncate(self):
        truncate = FileViewer(make_file('dictionary-test.xpi')).truncate
        for x, y in (['foo.rdf', 'foo.rdf'],
                     ['somelongfilename.rdf', 'somelongfilenam...rdf'],
                     [u'unicode삮.txt', u'unicode\uc0ae.txt'],
                     [u'unicodesomelong삮.txt', u'unicodesomelong...txt'],
                     ['somelongfilename.somelongextension',
                      'somelongfilenam...somelonge..'],):
            assert truncate(x) == y

    def test_get_files_not_extracted_runs_extraction(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        assert not viewer.is_extracted()
        viewer.get_files()
        assert viewer.is_extracted()

    def test_get_files_size(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        viewer.extract()
        files = viewer.get_files()
        assert len(files) == 14

    def test_syntax(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        for filename, syntax in [('foo.rdf', 'xml'),
                                 ('foo.xul', 'xml'),
                                 ('foo.json', 'js'),
                                 ('foo.jsm', 'js'),
                                 ('foo.htm', 'html'),
                                 ('foo.bar', 'plain'),
                                 ('foo.diff', 'plain')]:
            assert viewer.get_syntax(filename) == syntax

    @patch.object(settings, 'FILE_VIEWER_SIZE_LIMIT', 5)
    def test_file_size(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        viewer.extract()
        viewer.get_files()
        viewer.select('install.js')
        res = viewer.read_file()
        assert res == ''
        assert viewer.selected['msg'].startswith('File size is')

    @pytest.mark.needs_locales_compilation
    @patch.object(settings, 'FILE_VIEWER_SIZE_LIMIT', 5)
    def test_file_size_unicode(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        with self.activate(locale='he'):
            viewer.extract()
            viewer.get_files()
            viewer.select('install.js')
            res = viewer.read_file()
            assert res == ''
            assert (
                viewer.selected['msg'].startswith(u'גודל הקובץ חורג'))

    def test_default(self):
        viewer = FileViewer(make_file('dictionary-test.xpi'))
        assert viewer.extract()
        assert viewer.get_selected_file() == 'install.rdf'

    def test_default_webextension(self):
        viewer = FileViewer(make_file('webextension.xpi'))
        viewer.extract()
        assert viewer.get_selected_file() == 'manifest.json'

    def test_default_webextension_zip(self):
        viewer = FileViewer(make_file('webextension_no_id.zip'))
        viewer.extract()
        assert viewer.get_selected_file() == 'manifest.json'

    def test_default_webextension_crx(self):
        viewer = FileViewer(make_file('webextension.crx'))
        viewer.extract()
        assert viewer.get_selected_file() == 'manifest.json'

    def test_default_package_json(self):
        viewer = FileViewer(make_file('new-format-0.0.1.xpi'))
        viewer.extract()
        assert viewer.get_selected_file() == 'package.json'


class TestSearchEngineHelper(TestCase):
    fixtures = ['base/addon_4594_a9']

    def setUp(self):
        super(TestSearchEngineHelper, self).setUp()
        self.left = File.objects.get(pk=25753)
        viewer = FileViewer(self.left)

    def test_is_search_engine(self):
        assert viewer.is_search_engine()

    def test_default(self):
        viewer.extract()
        assert viewer.get_selected_file() == 'a9.xml'


class TestDiffSearchEngine(TestCase):

    def setUp(self):
        super(TestDiffSearchEngine, self).setUp()
        self.helper = DiffHelper(make_file('search.xml'),
                                 make_file('search.xml'))

    def test_diff_search(self):
        self.helper.extract()
        assert self.helper.select('search.xml')
        assert len(self.helper.get_deleted_files()) == 0


class TestDiffHelper(TestCase):

    def setUp(self):
        super(TestDiffHelper, self).setUp()
        self.helper = DiffHelper(
            make_file('dictionary-test.xpi'),
            make_file('dictionary-test.xpi'))

    def clear_cache(self):
        cache.delete(self.helper.left._cache_key())
        cache.delete(self.helper.right._cache_key())

    def test_files_not_extracted(self):
        assert not self.helper.is_extracted()

    def test_files_extracted(self):
        self.helper.extract()
        assert self.helper.is_extracted()

    def test_get_files(self):
        assert self.helper.left.get_files() == (
            self.helper.get_files())

    def test_diffable(self):
        self.helper.extract()
        self.helper.select('install.js')
        assert self.helper.is_diffable()

    def test_diffable_allow_empty(self):
        self.helper.extract()
        self.assertRaises(AssertionError, self.helper.right.read_file)
        assert self.helper.right.read_file(allow_empty=True) == ''

    def test_diffable_both_missing(self):
        self.helper.extract()
        self.helper.select('foo.js')
        assert not self.helper.is_diffable()

    def test_diffable_one_binary_same(self):
        self.helper.extract()
        self.helper.select('install.js')
        self.helper.left.selected['binary'] = True
        assert self.helper.is_binary()

    def test_diffable_one_binary_diff(self):
        self.helper.extract()
        self.change(self.helper.left.dest, 'asd')
        self.helper.select('install.js')
        self.helper.left.selected['binary'] = True
        assert self.helper.is_binary()

    def test_diffable_two_binary_diff(self):
        self.helper.extract()
        self.change(self.helper.left.dest, 'asd')
        self.change(self.helper.right.dest, 'asd123')
        self.clear_cache()
        self.helper.select('install.js')
        self.helper.left.selected['binary'] = True
        self.helper.right.selected['binary'] = True
        assert self.helper.is_binary()

    def test_diffable_one_directory(self):
        self.helper.extract()
        self.helper.select('install.js')
        self.helper.left.selected['directory'] = True
        assert not self.helper.is_diffable()
        assert self.helper.left.selected['msg'].startswith('This file')

    def test_diffable_parent(self):
        self.helper.extract()
        self.change(self.helper.left.dest, 'asd',
                    filename='__MACOSX/._dictionaries')
        self.clear_cache()
        files = self.helper.get_files()
        assert files['__MACOSX/._dictionaries']['diff']
        assert files['__MACOSX']['diff']

    def change(self, file, text, filename='install.js'):
        path = os.path.join(file, filename)
        data = open(path, 'r').read()
        data += text
        open(path, 'w').write(data)


class TestSafeZipFile(TestCase, amo.tests.AMOPaths):

    # TODO(andym): get full coverage for existing SafeZip methods, most
    # is covered in the file viewer tests.
    @patch.object(settings, 'FILE_UNZIP_SIZE_LIMIT', 5)
    def test_unzip_limit(self):
        with pytest.raises(forms.ValidationError):
            SafeZip(self.xpi_path('langpack-localepicker'))

    def test_unzip_fatal(self):
        with pytest.raises(zipfile.BadZipfile):
            SafeZip(self.xpi_path('search.xml'))

    def test_read(self):
        zip_file = SafeZip(self.xpi_path('langpack-localepicker'))
        assert zip_file.is_valid
        assert 'locale browser de' in zip_file.read('chrome.manifest')

    def test_invalid_zip_encoding(self):
        with pytest.raises(forms.ValidationError) as exc:
            SafeZip(self.xpi_path('invalid-cp437-encoding.xpi'))

        assert isinstance(exc.value, forms.ValidationError)
        assert exc.value.message.endswith(
            'Please make sure all filenames are utf-8 or latin1 encoded.')

    def test_not_secure(self):
        zip_file = SafeZip(self.xpi_path('extension'))
        assert not zip_file.is_signed()

    def test_is_secure(self):
        zip_file = SafeZip(self.xpi_path('signed'))
        assert zip_file.is_signed()

    def test_is_broken(self):
        zip_file = SafeZip(self.xpi_path('signed'))
        zip_file.info_list[2].filename = 'META-INF/foo.sf'
        assert not zip_file.is_signed()
