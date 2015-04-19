# -*- coding: utf-8 -*-
import os
import zipfile

from django.conf import settings
from django.test.utils import override_settings

import mock
import pytest

import amo
import amo.tests
from files.utils import parse_xpi
from lib.crypto import packaged, tasks


@override_settings(SIGNING_SERVER='http://full',
                   PRELIMINARY_SIGNING_SERVER='http://prelim')
class TestPackaged(amo.tests.TestCase):

    def setUp(self):
        super(TestPackaged, self).setUp()

        # Change addon file name
        self.addon = amo.tests.addon_factory()
        self.addon.update(guid='xxxxx')
        self.version = self.addon.current_version
        self.file1 = self.version.all_files[0]
        self.file1.update(filename='addon-a.xpi')

        self.file2 = amo.tests.file_factory(version=self.version)
        self.file2.update(filename='addon-b.xpi')
        # Update the "all_files" cached property.
        self.version.all_files.append(self.file2)

        # Add actual file to addons
        if not os.path.exists(os.path.dirname(self.file1.file_path)):
            os.makedirs(os.path.dirname(self.file1.file_path))

        for f in (self.file1, self.file2):
            fp = zipfile.ZipFile(f.file_path, 'w')
            fp.writestr('install.rdf', '<?xml version="1.0"?><RDF></RDF>')
            fp.close()

    def tearDown(self):
        for f in (self.file1, self.file2):
            if os.path.exists(f.file_path):
                os.unlink(f.file_path)
        super(TestPackaged, self).tearDown()

    @pytest.fixture(autouse=True)
    def mock_post(self, monkeypatch):
        """Fake a standard trunion response."""
        class FakeResponse:
            status_code = 200
            content = '{"mozilla.rsa": ""}'

        monkeypatch.setattr(
            'requests.post', lambda url, timeout, data, files: FakeResponse)

    @pytest.fixture(autouse=True)
    def mock_get_signature_serial_number(self, monkeypatch):
        """Fake a standard signing-client response."""
        monkeypatch.setattr('lib.crypto.packaged.get_signature_serial_number',
                            lambda pkcs7: 'serial number')

    def test_get_endpoint(self):
        assert self.addon.status == amo.STATUS_PUBLIC
        with self.settings(PRELIMINARY_SIGNING_SERVER=''):
            assert packaged.get_endpoint(self.file1).startswith('http://full')
        self.addon.update(status=amo.STATUS_LITE)
        with self.settings(SIGNING_SERVER=''):
            assert packaged.get_endpoint(self.file1).startswith(
                'http://prelim')

    def test_no_file(self):
        [f.delete() for f in self.addon.current_version.all_files]
        with pytest.raises(packaged.SigningError):
            packaged.sign(self.version)

    def test_non_xpi(self):
        self.file1.update(filename='foo.txt')
        with pytest.raises(packaged.SigningError):
            packaged.sign_file(self.file1)

    def test_no_server_full(self):
        with self.settings(SIGNING_SERVER=''):
            packaged.sign(self.version)
        # Make sure the files weren't signed.
        assert not self.file1.is_signed
        assert not self.file2.is_signed
        assert not self.file1.cert_serial_num
        assert not self.file2.cert_serial_num

    def test_no_server_prelim(self):
        self.file1.update(status=amo.STATUS_LITE)
        self.file2.update(status=amo.STATUS_LITE)
        with self.settings(PRELIMINARY_SIGNING_SERVER=''):
            packaged.sign(self.version)
        # Make sure the files weren't signed.
        assert not self.file1.is_signed
        assert not self.file2.is_signed
        assert not self.file1.cert_serial_num
        assert not self.file2.cert_serial_num

    def test_sign_file(self):
        assert not self.file1.is_signed
        assert not self.file2.is_signed
        assert not self.file1.cert_serial_num
        assert not self.file2.cert_serial_num
        assert not self.file1.hash
        assert not self.file2.hash
        packaged.sign(self.version)
        assert self.file1.is_signed
        assert self.file2.is_signed
        assert self.file1.cert_serial_num
        assert self.file2.cert_serial_num
        assert self.file1.hash
        assert self.file2.hash

    def test_no_sign_hotfix_addons(self):
        """Don't sign hotfix addons."""
        for hotfix_guid in settings.HOTFIX_ADDON_GUIDS:
            self.addon.update(guid=hotfix_guid)
            packaged.sign(self.version)
            assert not self.file1.is_signed
            assert not self.file2.is_signed
            assert not self.file1.cert_serial_num
            assert not self.file2.cert_serial_num
            assert not self.file1.hash
            assert not self.file2.hash


class TestTasks(amo.tests.TestCase):

    def setUp(self):
        super(TestTasks, self).setUp()
        self.addon = amo.tests.addon_factory(version_kw={'version': '1.3'})
        self.version = self.addon.current_version
        self.file1 = self.version.all_files[0]
        self.file1.update(filename='jetpack.xpi')

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_bump_version_in_model(self, mock_sign_file):
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file1.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_resign_dont_bump_version_in_model(self, mock_sign_file):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-addon-signature.xpi',
                self.file1.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_version_bad_zipfile(self, mock_sign_file):
        with amo.tests.copy_file(__file__, self.file1.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_resign_bump_version_in_model_if_force(self, mock_sign_file):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-addon-signature.xpi',
                self.file1.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk], force=True)
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1'

    def test_bump_version_in_install_rdf(self):
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file1.file_path):
            tasks.bump_version_number(self.file1)
            parsed = parse_xpi(self.file1.file_path)
            assert parsed['version'] == '1.3.1'

    def test_bump_version_in_alt_install_rdf(self):
        with amo.tests.copy_file('apps/files/fixtures/files/alt-rdf.xpi',
                                 self.file1.file_path):
            tasks.bump_version_number(self.file1)
            parsed = parse_xpi(self.file1.file_path)
            assert parsed['version'] == '2.1.106.1'

    def test_bump_version_in_package_json(self):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-format-0.0.1.xpi',
                self.file1.file_path):
            tasks.bump_version_number(self.file1)
            parsed = parse_xpi(self.file1.file_path)
            assert parsed['version'] == '0.0.1.1'
