import json
import os
import tempfile
import zipfile

from unittest import mock
from waffle.testutils import override_switch

from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.files.tasks import repack_fileupload
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import SafeZip
from olympia.files.tests.test_utils import AppVersionsMixin


class TestRepackFileUpload(AppVersionsMixin, UploadMixin, TestCase):
    @mock.patch('olympia.amo.utils.SafeStorage.move_stored_file')
    @mock.patch('olympia.files.tasks.get_sha256')
    @mock.patch('olympia.files.tasks.shutil')
    @mock.patch.object(SafeZip, 'extract_to_dest')
    def test_repacking_xpi_files_with_mocks(
        self, extract_to_dest_mock, shutil_mock, get_sha256_mock, move_stored_file_mock
    ):
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
        tmp_dir_before_repacking = sorted(os.listdir(tempfile.gettempdir()))
        repack_fileupload(fake_results, upload.pk)
        upload.reload()
        assert upload.hash.startswith('sha256:')
        assert upload.hash != original_hash

        # Test zip contents
        with zipfile.ZipFile(upload.path) as z:
            contents = sorted(z.namelist())
            assert contents == [
                'index.js',
                'manifest.json',
                '삮',
            ]
        # Spot-check an individual file.
        info = z.getinfo('manifest.json')
        assert info.file_size == 240
        assert info.compress_size < info.file_size
        assert info.compress_type == zipfile.ZIP_DEFLATED
        # Check we cleaned up after ourselves: we shouldn't have left anything
        # in /tmp.
        assert tmp_dir_before_repacking == sorted(os.listdir(tempfile.gettempdir()))

    @override_switch('enable-manifest-normalization', active=False)
    def test_does_not_normalize_manifest_json_when_switch_is_inactive(self):
        upload = self.get_upload('webextension.xpi')
        fake_results = {'errors': 0}
        manifest_with_comments = """
        {
            // Required
            "manifest_version": 2,
            "name": "My Extension",
            "version": "versionString",
            // Recommended
            "description": "haupt\\u005fstra\\u00dfe"
        }
        """
        with zipfile.ZipFile(upload.path, 'w') as z:
            z.writestr('manifest.json', manifest_with_comments)

        repack_fileupload(fake_results, upload.pk)
        upload.reload()

        with zipfile.ZipFile(upload.path) as z:
            with z.open('manifest.json') as manifest:
                assert manifest.read().decode() == manifest_with_comments

    @override_switch('enable-manifest-normalization', active=True)
    def test_does_not_normalize_manifest_json_when_addon_is_signed(self):
        upload = self.get_upload('webextension_signed_already.xpi')
        fake_results = {'errors': 0}
        with zipfile.ZipFile(upload.path, 'r') as z:
            with z.open('manifest.json') as manifest:
                original_manifest = manifest.read().decode()

        repack_fileupload(fake_results, upload.pk)
        upload.reload()

        with zipfile.ZipFile(upload.path) as z:
            with z.open('manifest.json') as manifest:
                assert manifest.read().decode() == original_manifest

    @override_switch('enable-manifest-normalization', active=True)
    def test_normalize_manifest_json_with_bom(self):
        upload = self.get_upload('webextension.xpi')
        fake_results = {'errors': 0}
        with zipfile.ZipFile(upload.path, 'w') as z:
            manifest = b'\xef\xbb\xbf{"manifest_version": 2, "name": "..."}'
            z.writestr('manifest.json', manifest)

        repack_fileupload(fake_results, upload.pk)
        upload.reload()

        with zipfile.ZipFile(upload.path) as z:
            with z.open('manifest.json') as manifest:
                # Make sure it is valid JSON
                assert json.loads(manifest.read())
                manifest.seek(0)
                assert manifest.read().decode() == '\n'.join(
                    [
                        '{',
                        '  "manifest_version": 2,',
                        '  "name": "..."',
                        '}',
                    ]
                )

    @override_switch('enable-manifest-normalization', active=True)
    def test_normalize_manifest_json_with_missing_manifest(self):
        # This file does not have a manifest.json at all but it does not matter
        # since we expect the manifest file to be at the root of the archive.
        upload = self.get_upload('directory-test.xpi')
        fake_results = {'errors': 0}

        results = repack_fileupload(fake_results, upload.pk)

        # If there is an error raised somehow, the `@validation_task` decorator
        # will catch it and return an error.
        assert results['errors'] == 0

    @override_switch('enable-manifest-normalization', active=True)
    def test_normalize_manifest_json_with_syntax_error(self):
        upload = self.get_upload('webextension.xpi')
        fake_results = {'errors': 0}
        with zipfile.ZipFile(upload.path, 'w') as z:
            manifest = b'{"manifest_version": 2, THIS_IS_INVALID }'
            z.writestr('manifest.json', manifest)

        results = repack_fileupload(fake_results, upload.pk)

        # If there is an error raised somehow, the `@validation_task` decorator
        # will catch it and return an error.
        assert results['errors'] == 0

    @override_switch('enable-manifest-normalization', active=True)
    def test_normalize_manifest_json(self):
        upload = self.get_upload('webextension.xpi')
        fake_results = {'errors': 0}
        with zipfile.ZipFile(upload.path, 'w') as z:
            manifest_with_comments = """
            {
                // Required
                "manifest_version": 2,
                "name": "My Extension",
                "version": "versionString",
                // Recommended
                "description": "haupt\\u005fstra\\u00dfe"
            }
            """
            z.writestr('manifest.json', manifest_with_comments)

        repack_fileupload(fake_results, upload.pk)
        upload.reload()

        with zipfile.ZipFile(upload.path) as z:
            with z.open('manifest.json') as manifest:
                # Make sure it is valid JSON
                assert json.loads(manifest.read())
                # Read the content again to make sure comments have been
                # removed with a string comparison.
                manifest.seek(0)
                assert manifest.read().decode() == '\n'.join(
                    [
                        '{',
                        '  "manifest_version": 2,',
                        '  "name": "My Extension",',
                        '  "version": "versionString",',
                        '  "description": "haupt_stra\\u00dfe"',
                        '}',
                    ]
                )
