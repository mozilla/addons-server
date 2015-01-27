# -*- coding: utf-8 -*-
import os
import zipfile

from django.test.utils import override_settings

import pytest

import amo
import amo.tests
from lib.crypto import packaged


def is_signed(filename):
    """Return True if the file has been signed."""
    zf = zipfile.ZipFile(filename, mode='r')
    filenames = zf.namelist()
    return ('META-INF/zigbert.rsa' in filenames and
            'META-INF/zigbert.sf' in filenames and
            'META-INF/manifest.mf' in filenames)


@override_settings(SIGNING_SERVER='http://foo')
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
            content = '{"zigbert.rsa": ""}'

        monkeypatch.setattr(
            'requests.post', lambda url, timeout, data, files: FakeResponse)

    def test_no_file(self):
        [f.delete() for f in self.addon.current_version.all_files]
        with pytest.raises(packaged.SigningError):
            packaged.sign(self.version)

    def test_non_xpi(self):
        self.file1.update(filename='foo.txt')
        with pytest.raises(packaged.SigningError):
            packaged.sign_file(self.file1)

    def test_server_active(self):
        with self.settings(SIGNING_SERVER=""):
            packaged.sign(self.version)
        # Make sure the file wasn't signed.
        assert not is_signed(self.file1.file_path)

    def test_sign_file(self):
        with self.settings(SIGNING_REVIEWER_SERVER_ACTIVE=True,
                           SIGNING_SERVER='http://sign.me'):
            packaged.sign(self.version)
        assert is_signed(self.file1.file_path)
