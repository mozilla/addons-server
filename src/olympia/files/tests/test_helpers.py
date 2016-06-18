# -*- coding: utf-8 -*-
import os
import mimetypes
import shutil
import zipfile

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django import forms

from mock import Mock, patch

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.files.helpers import FileViewer, DiffHelper
from olympia.files.models import File
from olympia.files.utils import SafeUnzip

root = os.path.join(settings.ROOT, 'src/olympia/files/fixtures/files')


def get_file(filename):
    return os.path.join(root, filename)


def make_file(pk, file_path, **kwargs):
    obj = Mock()
    obj.id = obj.pk = pk
    for k, v in kwargs.items():
        setattr(obj, k, v)
    obj.file_path = file_path
    obj.current_file_path = file_path
    obj.__str__ = lambda x: x.pk
    obj.version = Mock()
    obj.version.version = 1
    return obj


class TestFileHelper(TestCase):

    def setUp(self):
        super(TestFileHelper, self).setUp()
        self.viewer = FileViewer(make_file(1, get_file('dictionary-test.xpi')))

    def tearDown(self):
        self.viewer.cleanup()
        super(TestFileHelper, self).tearDown()

    def test_files_not_extracted(self):
        assert not self.viewer.is_extracted()

    def test_files_extracted(self):
        self.viewer.extract()
        assert self.viewer.is_extracted()

    def test_recurse_extract(self):
        self.viewer.src = get_file('recurse.xpi')
        self.viewer.extract()
        assert self.viewer.is_extracted()

    def test_recurse_contents(self):
        self.viewer.src = get_file('recurse.xpi')
        self.viewer.extract()
        files = self.viewer.get_files()
        file_list = [
            'recurse/recurse.xpi/chrome/test-root.txt',
            'recurse/somejar.jar/recurse/recurse.xpi/chrome/test.jar',
            'recurse/somejar.jar/recurse/recurse.xpi/chrome/test.jar/test'
        ]
        for name in file_list:
            assert name in files

    def test_recurse_contents_of_zip(self):
        self.viewer.src = get_file('recurse.zip')
        self.viewer.extract()
        files = self.viewer.get_files()
        file_list = [
            'recurse/recurse.xpi/chrome/test-root.txt',
            'recurse/somejar.jar/recurse/recurse.xpi/chrome/test.jar',
            'recurse/somejar.jar/recurse/recurse.xpi/chrome/test.jar/test'
        ]
        for name in file_list:
            assert name in files

    def test_cleanup(self):
        self.viewer.extract()
        self.viewer.cleanup()
        assert not self.viewer.is_extracted()

    def test_isbinary(self):
        binary = self.viewer._is_binary
        for f in ['foo.rdf', 'foo.xml', 'foo.js', 'foo.py'
                  'foo.html', 'foo.txt', 'foo.dtd', 'foo.xul', 'foo.sh',
                  'foo.properties', 'foo.json', 'foo.src', 'CHANGELOG']:
            m, encoding = mimetypes.guess_type(f)
            assert not binary(m, f), '%s should not be binary' % f

        for f in ['foo.png', 'foo.gif', 'foo.exe', 'foo.swf']:
            m, encoding = mimetypes.guess_type(f)
            assert binary(m, f), '%s should be binary' % f

        filename = os.path.join(settings.TMP_PATH, 'test_isbinary')
        for txt in ['#!/usr/bin/python', '#python', u'\0x2']:
            open(filename, 'w').write(txt)
            m, encoding = mimetypes.guess_type(filename)
            assert not binary(m, filename), '%s should not be binary' % txt

        for txt in ['MZ']:
            open(filename, 'w').write(txt)
            m, encoding = mimetypes.guess_type(filename)
            assert binary(m, filename), '%s should be binary' % txt
        os.remove(filename)

    def test_truncate(self):
        truncate = self.viewer.truncate
        for x, y in (['foo.rdf', 'foo.rdf'],
                     ['somelongfilename.rdf', 'somelongfilenam...rdf'],
                     [u'unicode삮.txt', u'unicode\uc0ae.txt'],
                     [u'unicodesomelong삮.txt', u'unicodesomelong...txt'],
                     ['somelongfilename.somelongextension',
                      'somelongfilenam...somelonge..'],):
            assert truncate(x) == y

    def test_get_files_not_extracted(self):
        assert not self.viewer.get_files()

    def test_get_files_size(self):
        self.viewer.extract()
        files = self.viewer.get_files()
        assert len(files) == 14

    def test_get_files_directory(self):
        self.viewer.extract()
        files = self.viewer.get_files()
        assert not files['install.js']['directory']
        assert not files['install.js']['binary']
        assert files['__MACOSX']['directory']
        assert not files['__MACOSX']['binary']

    def test_url_file(self):
        self.viewer.extract()
        files = self.viewer.get_files()
        url = reverse('files.list', args=[self.viewer.file.id,
                                          'file', 'install.js'])
        file_url = files['install.js']['url']
        assert file_url == url
        assert file_url.startswith('/en-US')

        # Make sure that the locale is properly used (see bug 1168794).
        with self.activate('fr'):
            self.viewer._files = {}  # Reset the viewer's internal cache.
            files = self.viewer.get_files()
            url = reverse('files.list', args=[self.viewer.file.id,
                                              'file', 'install.js'])
            file_url = files['install.js']['url']
            assert file_url == url
            assert file_url.startswith('/fr')

    def test_get_files_depth(self):
        self.viewer.extract()
        files = self.viewer.get_files()
        assert files['dictionaries/license.txt']['depth'] == 1

    def test_bom(self):
        dest = os.path.join(settings.TMP_PATH, 'test_bom')
        open(dest, 'w').write('foo'.encode('utf-16'))
        self.viewer.select('foo')
        self.viewer.selected = {'full': dest, 'size': 1}
        assert self.viewer.read_file() == u'foo'
        os.remove(dest)

    def test_syntax(self):
        for filename, syntax in [('foo.rdf', 'xml'),
                                 ('foo.xul', 'xml'),
                                 ('foo.json', 'js'),
                                 ('foo.jsm', 'js'),
                                 ('foo.bar', 'plain')]:
            assert self.viewer.get_syntax(filename) == syntax

    def test_file_order(self):
        self.viewer.extract()
        dest = self.viewer.dest
        open(os.path.join(dest, 'chrome.manifest'), 'w')
        subdir = os.path.join(dest, 'chrome')
        os.mkdir(subdir)
        open(os.path.join(subdir, 'foo'), 'w')
        cache.clear()
        files = self.viewer.get_files().keys()
        rt = files.index(u'chrome')
        assert files[rt:rt + 3] == [u'chrome', u'chrome/foo', u'dictionaries']

    @patch.object(settings, 'FILE_VIEWER_SIZE_LIMIT', 5)
    def test_file_size(self):
        self.viewer.extract()
        self.viewer.get_files()
        self.viewer.select('install.js')
        res = self.viewer.read_file()
        assert res == ''
        assert self.viewer.selected['msg'].startswith('File size is')

    @patch.object(settings, 'FILE_VIEWER_SIZE_LIMIT', 5)
    def test_file_size_unicode(self):
        with self.activate(locale='he'):
            self.viewer.extract()
            self.viewer.get_files()
            self.viewer.select('install.js')
            res = self.viewer.read_file()
            assert res == ''
            assert self.viewer.selected['msg'].startswith('File size is')

    @patch.object(settings, 'FILE_UNZIP_SIZE_LIMIT', 5)
    def test_contents_size(self):
        self.assertRaises(forms.ValidationError, self.viewer.extract)

    def test_default(self):
        self.viewer.extract()
        assert self.viewer.get_default(None) == 'install.rdf'

    def test_default_webextension(self):
        viewer = FileViewer(make_file(2, get_file('webextension.xpi')))
        viewer.extract()
        assert viewer.get_default(None) == 'manifest.json'

    def test_default_webextension_zip(self):
        viewer = FileViewer(make_file(2, get_file('webextension_no_id.zip')))
        viewer.extract()
        assert viewer.get_default(None) == 'manifest.json'

    def test_default_webextension_crx(self):
        viewer = FileViewer(make_file(2, get_file('webextension.crx')))
        viewer.extract()
        assert viewer.get_default(None) == 'manifest.json'

    def test_default_package_json(self):
        viewer = FileViewer(make_file(3, get_file('new-format-0.0.1.xpi')))
        viewer.extract()
        assert viewer.get_default(None) == 'package.json'

    def test_delete_mid_read(self):
        self.viewer.extract()
        self.viewer.select('install.js')
        os.remove(os.path.join(self.viewer.dest, 'install.js'))
        res = self.viewer.read_file()
        assert res == ''
        assert self.viewer.selected['msg'].startswith('That file no')

    @patch('olympia.files.helpers.get_md5')
    def test_delete_mid_tree(self, get_md5):
        get_md5.side_effect = IOError('ow')
        self.viewer.extract()
        assert {} == self.viewer.get_files()


class TestSearchEngineHelper(TestCase):
    fixtures = ['base/addon_4594_a9']

    def setUp(self):
        super(TestSearchEngineHelper, self).setUp()
        self.left = File.objects.get(pk=25753)
        self.viewer = FileViewer(self.left)

        if not os.path.exists(os.path.dirname(self.viewer.src)):
            os.makedirs(os.path.dirname(self.viewer.src))
            with storage.open(self.viewer.src, 'w') as f:
                f.write('some data\n')

    def tearDown(self):
        self.viewer.cleanup()
        super(TestSearchEngineHelper, self).tearDown()

    def test_is_search_engine(self):
        assert self.viewer.is_search_engine()

    def test_extract_search_engine(self):
        self.viewer.extract()
        assert os.path.exists(self.viewer.dest)

    def test_default(self):
        self.viewer.extract()
        assert self.viewer.get_default(None) == 'a9.xml'

    def test_default_no_files(self):
        self.viewer.extract()
        os.remove(os.path.join(self.viewer.dest, 'a9.xml'))
        assert self.viewer.get_default(None) is None


class TestDiffSearchEngine(TestCase):

    def setUp(self):
        super(TestDiffSearchEngine, self).setUp()
        src = os.path.join(settings.ROOT, get_file('search.xml'))
        if not storage.exists(src):
            with storage.open(src, 'w') as f:
                f.write(open(src).read())
        self.helper = DiffHelper(make_file(1, src, filename='search.xml'),
                                 make_file(2, src, filename='search.xml'))

    def tearDown(self):
        self.helper.cleanup()
        super(TestDiffSearchEngine, self).tearDown()

    @patch('olympia.files.helpers.FileViewer.is_search_engine')
    def test_diff_search(self, is_search_engine):
        is_search_engine.return_value = True
        self.helper.extract()
        shutil.copyfile(os.path.join(self.helper.left.dest, 'search.xml'),
                        os.path.join(self.helper.right.dest, 's-20010101.xml'))
        assert self.helper.select('search.xml')
        assert len(self.helper.get_deleted_files()) == 0


class TestDiffHelper(TestCase):

    def setUp(self):
        super(TestDiffHelper, self).setUp()
        src = os.path.join(settings.ROOT, get_file('dictionary-test.xpi'))
        self.helper = DiffHelper(make_file(1, src), make_file(2, src))

    def tearDown(self):
        self.helper.cleanup()
        super(TestDiffHelper, self).tearDown()

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

    def test_diffable_one_missing(self):
        self.helper.extract()
        os.remove(os.path.join(self.helper.right.dest, 'install.js'))
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

    def test_diffable_deleted_files(self):
        self.helper.extract()
        os.remove(os.path.join(self.helper.left.dest, 'install.js'))
        assert 'install.js' in self.helper.get_deleted_files()

    def test_diffable_one_binary_same(self):
        self.helper.extract()
        self.helper.select('install.js')
        self.helper.left.selected['binary'] = True
        assert self.helper.is_binary()

    def test_diffable_one_binary_diff(self):
        self.helper.extract()
        self.change(self.helper.left.dest, 'asd')
        cache.clear()
        self.helper.select('install.js')
        self.helper.left.selected['binary'] = True
        assert self.helper.is_binary()

    def test_diffable_two_binary_diff(self):
        self.helper.extract()
        self.change(self.helper.left.dest, 'asd')
        self.change(self.helper.right.dest, 'asd123')
        cache.clear()
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
        cache.clear()
        files = self.helper.get_files()
        assert files['__MACOSX/._dictionaries']['diff']
        assert files['__MACOSX']['diff']

    def change(self, file, text, filename='install.js'):
        path = os.path.join(file, filename)
        data = open(path, 'r').read()
        data += text
        open(path, 'w').write(data)


class TestSafeUnzipFile(TestCase, amo.tests.AMOPaths):

    # TODO(andym): get full coverage for existing SafeUnzip methods, most
    # is covered in the file viewer tests.
    @patch.object(settings, 'FILE_UNZIP_SIZE_LIMIT', 5)
    def test_unzip_limit(self):
        zip_file = SafeUnzip(self.xpi_path('langpack-localepicker'))
        self.assertRaises(forms.ValidationError, zip_file.is_valid)

    def test_unzip_fatal(self):
        zip_file = SafeUnzip(self.xpi_path('search.xml'))
        self.assertRaises(zipfile.BadZipfile, zip_file.is_valid)

    def test_unzip_not_fatal(self):
        zip_file = SafeUnzip(self.xpi_path('search.xml'))
        assert not zip_file.is_valid(fatal=False)

    def test_extract_path(self):
        zip_file = SafeUnzip(self.xpi_path('langpack-localepicker'))
        assert zip_file.is_valid()
        assert'locale browser de' in zip_file.extract_path('chrome.manifest')

    def test_not_secure(self):
        zip_file = SafeUnzip(self.xpi_path('extension'))
        zip_file.is_valid()
        assert not zip_file.is_signed()

    def test_is_secure(self):
        zip_file = SafeUnzip(self.xpi_path('signed'))
        zip_file.is_valid()
        assert zip_file.is_signed()

    def test_is_broken(self):
        zip_file = SafeUnzip(self.xpi_path('signed'))
        zip_file.is_valid()
        zip_file.info_list[2].filename = 'META-INF/foo.sf'
        assert not zip_file.is_signed()
