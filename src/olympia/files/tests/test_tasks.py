# -*- coding: utf-8 -*-
from unittest import mock
import tempfile
import zipfile

from django.conf import settings

from olympia.amo.tests import TestCase, addon_factory
from olympia.files.tasks import repack_fileupload, hide_disabled_files
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import SafeZip


class TestRepackFileUpload(UploadTest, TestCase):
    @mock.patch('olympia.files.tasks.move_stored_file')
    @mock.patch('olympia.files.tasks.get_sha256')
    @mock.patch('olympia.files.tasks.shutil')
    @mock.patch.object(SafeZip, 'extract_to_dest')
    def test_not_repacking_non_xpi_files_with_mocks(
            self, extract_to_dest_mock, shutil_mock, get_sha256_mock,
            move_stored_file_mock):
        """Test we're not repacking non-xpi files"""
        upload = self.get_upload('search.xml')
        old_hash = upload.hash
        assert old_hash.startswith('sha256:')
        fake_results = {'errors': 0}
        repack_fileupload(fake_results, upload.pk)
        assert not extract_to_dest_mock.called
        assert not shutil_mock.make_archive.called
        assert not get_sha256_mock.called
        assert not move_stored_file_mock.called
        upload.reload()
        assert upload.hash == old_hash  # Hasn't changed.

    @mock.patch('olympia.files.tasks.move_stored_file')
    @mock.patch('olympia.files.tasks.get_sha256')
    @mock.patch('olympia.files.tasks.shutil')
    @mock.patch.object(SafeZip, 'extract_to_dest')
    def test_repacking_xpi_files_with_mocks(
            self, extract_to_dest_mock, shutil_mock, get_sha256_mock,
            move_stored_file_mock):
        """Opposite of test_not_repacking_non_xpi_files() (using same mocks)"""
        upload = self.get_upload('webextension.xpi')
        get_sha256_mock.return_value = 'fakehashfrommock'
        fake_results = {'errors': 0}
        repack_fileupload(fake_results, upload.pk)
        assert extract_to_dest_mock.called
        tempdir = extract_to_dest_mock.call_args[0][0]
        assert tempdir.startswith(tempfile.gettempdir())  # On local filesystem
        assert not tempdir.startswith(settings.TMP_PATH)  # Not on EFS
        assert shutil_mock.make_archive.called
        assert get_sha256_mock.called
        assert move_stored_file_mock.called
        upload.reload()
        assert upload.hash == 'sha256:fakehashfrommock'

    def test_repacking_xpi_files(self):
        """Test that repack_fileupload() does repack xpi files (no mocks)"""
        # Take an extension with a directory structure, so that we can test
        # that structure is restored once the file has been moved.
        upload = self.get_upload('unicode-filenames.xpi')
        original_hash = upload.hash
        fake_results = {'errors': 0}
        repack_fileupload(fake_results, upload.pk)
        upload.reload()
        assert upload.hash.startswith('sha256:')
        assert upload.hash != original_hash

        # Test zip contents
        with zipfile.ZipFile(upload.path) as z:
            contents = sorted(z.namelist())
            assert contents == [
                u'chrome.manifest',
                u'chrome/',
                u'chrome/content/',
                u'chrome/content/ff-overlay.js',
                u'chrome/content/ff-overlay.xul',
                u'chrome/content/overlay.js',
                u'chrome/locale/',
                u'chrome/locale/en-US/',
                u'chrome/locale/en-US/overlay.dtd',
                u'chrome/locale/en-US/overlay.properties',
                u'chrome/skin/',
                u'chrome/skin/overlay.css',
                u'install.rdf',
                u'삮'
            ]
        # Spot-check an individual file.
        info = z.getinfo('install.rdf')
        assert info.file_size == 717
        assert info.compress_size < info.file_size
        assert info.compress_type == zipfile.ZIP_DEFLATED


class TestHideDisabledFile(TestCase):
    msg = 'Moving disabled file: {source} => {destination}'

    def setUp(self):
        self.addon1 = addon_factory()
        self.addon2 = addon_factory()
        self.file1 = self.addon1.current_version.all_files[0]

    @mock.patch('olympia.files.models.File.move_file')
    def test_hide_disabled_files(self, move_file_mock):
        hide_disabled_files.delay(addon_id=self.addon1.id)
        move_file_mock.assert_called_once_with(
            self.file1.file_path,
            self.file1.guarded_file_path,
            self.msg
        )
