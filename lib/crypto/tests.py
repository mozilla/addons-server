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
        self.file_ = self.version.all_files[0]
        self.file_.update(filename='addon-a.xpi')

        # Add actual file to addons
        if not os.path.exists(os.path.dirname(self.file_.file_path)):
            os.makedirs(os.path.dirname(self.file_.file_path))

        fp = zipfile.ZipFile(self.file_.file_path, 'w')
        fp.writestr('install.rdf', '<?xml version="1.0"?><RDF></RDF>')
        fp.close()

    def tearDown(self):
        if os.path.exists(self.file_.file_path):
            os.unlink(self.file_.file_path)
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
            assert packaged.get_endpoint(self.file_).startswith('http://full')
        self.addon.update(status=amo.STATUS_LITE)
        with self.settings(SIGNING_SERVER=''):
            assert packaged.get_endpoint(self.file_).startswith(
                'http://prelim')
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        with self.settings(SIGNING_SERVER=''):
            assert packaged.get_endpoint(self.file_).startswith(
                'http://prelim')

    def test_no_server_full(self):
        with self.settings(SIGNING_SERVER=''):
            packaged.sign_file(self.file_)
        # Make sure the file wasn't signed.
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num

    def test_no_server_prelim(self):
        self.file_.update(status=amo.STATUS_LITE)
        with self.settings(PRELIMINARY_SIGNING_SERVER=''):
            packaged.sign_file(self.file_)
        # Make sure the file wasn't signed.
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num

        self.file_.update(status=amo.STATUS_LITE_AND_NOMINATED)
        with self.settings(PRELIMINARY_SIGNING_SERVER=''):
            packaged.sign_file(self.file_)
        # Make sure the file wasn't signed.
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num

    def test_sign_file(self):
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        packaged.sign_file(self.file_)
        assert self.file_.is_signed
        assert self.file_.cert_serial_num
        assert self.file_.hash

    def test_no_sign_hotfix_addons(self):
        """Don't sign hotfix addons."""
        for hotfix_guid in settings.HOTFIX_ADDON_GUIDS:
            self.addon.update(guid=hotfix_guid)
            packaged.sign_file(self.file_)
            assert not self.file_.is_signed
            assert not self.file_.cert_serial_num
            assert not self.file_.hash

    def test_no_sign_unreviewed(self):
        """Don't sign unreviewed files."""
        self.file_.update(status=amo.STATUS_UNREVIEWED)
        packaged.sign_file(self.file_)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        self.file_.update(status=amo.STATUS_NOMINATED)
        packaged.sign_file(self.file_)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash


class TestTasks(amo.tests.TestCase):

    def setUp(self):
        super(TestTasks, self).setUp()
        self.addon = amo.tests.addon_factory(version_kw={'version': '1.3'})
        self.version = self.addon.current_version
        self.file_ = self.version.all_files[0]
        self.file_.update(filename='jetpack.xpi')

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_bump_version_in_model(self, mock_sign_file):
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_resign_dont_bump_version_in_model(self, mock_sign_file):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-addon-signature.xpi',
                self.file_.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_version_bad_zipfile(self, mock_sign_file):
        with amo.tests.copy_file(__file__, self.file_.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_sign_error(self, mock_sign_file):
        mock_sign_file.side_effect = IOError()
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_resign_bump_version_in_model_if_force(self, mock_sign_file):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-addon-signature.xpi',
                self.file_.file_path):
            assert self.version.version == '1.3'
            tasks.sign_addons([self.addon.pk], force=True)
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'

    def test_bump_version_in_install_rdf(self):
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.file_path):
            tasks.bump_version_number(self.file_)
            parsed = parse_xpi(self.file_.file_path)
            assert parsed['version'] == '1.3.1-signed'

    def test_bump_version_in_alt_install_rdf(self):
        with amo.tests.copy_file('apps/files/fixtures/files/alt-rdf.xpi',
                                 self.file_.file_path):
            tasks.bump_version_number(self.file_)
            parsed = parse_xpi(self.file_.file_path)
            assert parsed['version'] == '2.1.106.1-signed'

    def test_bump_version_in_package_json(self):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-format-0.0.1.xpi',
                self.file_.file_path):
            tasks.bump_version_number(self.file_)
            parsed = parse_xpi(self.file_.file_path)
            assert parsed['version'] == '0.0.1.1-signed'
