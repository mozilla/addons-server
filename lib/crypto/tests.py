# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import zipfile

from django.conf import settings
from django.test.utils import override_settings

import mock
import pytest

import amo
import amo.tests
from files.utils import extract_xpi, parse_xpi
from lib.crypto import packaged, tasks
from versions.compare import version_int


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

    def assert_not_signed(self):
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        assert not packaged.is_signed(self.file_.file_path)

    def assert_signed(self):
        assert self.file_.is_signed
        assert self.file_.cert_serial_num
        assert self.file_.hash
        assert packaged.is_signed(self.file_.file_path)

    def test_supports_firefox_old_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and not default to compatible.
        max_appversion.update(version=settings.MIN_D2C_VERSION,
                              version_int=version_int(
                                  settings.MIN_D2C_VERSION))
        self.file_.update(binary_components=True, strict_compatibility=True)
        self.assert_not_signed()
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_not_signed()

    def test_supports_firefox_old_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and default to compatible.
        max_appversion.update(version=settings.MIN_D2C_VERSION,
                              version_int=version_int(
                                  settings.MIN_D2C_VERSION))
        self.file_.update(binary_components=False, strict_compatibility=False)
        self.assert_not_signed()
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_signed()

    def test_supports_firefox_recent_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Recent, not default to compatible.
        max_appversion.update(version=settings.MIN_NOT_D2C_VERSION,
                              version_int=version_int(
                                  settings.MIN_NOT_D2C_VERSION))
        self.file_.update(binary_components=True, strict_compatibility=True)
        self.assert_not_signed()
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_signed()

    def test_supports_firefox_recent_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Recent, default to compatible.
        max_appversion.update(version=settings.MIN_NOT_D2C_VERSION,
                              version_int=version_int(
                                  settings.MIN_NOT_D2C_VERSION))
        self.file_.update(binary_components=False, strict_compatibility=False)
        self.assert_not_signed()
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_signed()

    def test_get_endpoint(self):
        assert self.addon.status == amo.STATUS_PUBLIC
        with self.settings(PRELIMINARY_SIGNING_SERVER=''):
            assert packaged.get_endpoint(
                settings.SIGNING_SERVER).startswith('http://full')
        self.addon.update(status=amo.STATUS_LITE)
        with self.settings(SIGNING_SERVER=''):
            assert packaged.get_endpoint(
                settings.PRELIMINARY_SIGNING_SERVER).startswith(
                    'http://prelim')

    def test_no_server_full(self):
        with self.settings(SIGNING_SERVER=''):
            packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_not_signed()

    def test_no_server_prelim(self):
        with self.settings(PRELIMINARY_SIGNING_SERVER=''):
            packaged.sign_file(self.file_, settings.PRELIMINARY_SIGNING_SERVER)
        self.assert_not_signed()

    def test_sign_file(self):
        self.assert_not_signed()
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_signed()
        # Make sure there's two newlines at the end of the mozilla.sf file (see
        # bug 1158938).
        with zipfile.ZipFile(self.file_.file_path, mode='r') as zf:
            with zf.open('META-INF/mozilla.sf', 'r') as mozillasf:
                assert mozillasf.read().endswith('\n\n')

    def test_sign_file_non_ascii_filename(self):
        src = self.file_.file_path
        self.file_.update(filename=u'jétpack.xpi')
        shutil.move(src, self.file_.file_path)
        self.assert_not_signed()
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_signed()

    def test_no_sign_missing_file(self):
        os.unlink(self.file_.file_path)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        assert not packaged.is_signed(self.file_.file_path)

    def test_no_sign_hotfix_addons(self):
        """Don't sign hotfix addons."""
        for hotfix_guid in settings.HOTFIX_ADDON_GUIDS:
            self.addon.update(guid=hotfix_guid)
            packaged.sign_file(self.file_, settings.SIGNING_SERVER)
            self.assert_not_signed()

    def test_no_sign_unreviewed(self):
        """Don't sign unreviewed files."""
        self.file_.update(status=amo.STATUS_UNREVIEWED)
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_not_signed()

        self.file_.update(status=amo.STATUS_NOMINATED)
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        self.assert_not_signed()

    def test_is_signed(self):
        assert not packaged.is_signed(self.file_.file_path)
        packaged.sign_file(self.file_, settings.SIGNING_SERVER)
        assert packaged.is_signed(self.file_.file_path)

    def test_sign_file_multi_package(self):
        with amo.tests.copy_file('apps/files/fixtures/files/multi-package.xpi',
                                 self.file_.file_path,
                                 overwrite=True):
            self.file_.update(is_multi_package=True)
            self.assert_not_signed()
            # Make sure the internal XPIs aren't signed either.
            folder = tempfile.mkdtemp()
            try:
                extract_xpi(self.file_.file_path, folder)
                assert not packaged.is_signed(
                    os.path.join(folder, 'random_extension.xpi'))
                assert not packaged.is_signed(
                    os.path.join(folder, 'random_theme.xpi'))
            finally:
                amo.utils.rm_local_tmp_dir(folder)

            packaged.sign_file(self.file_, settings.SIGNING_SERVER)
            assert self.file_.is_signed
            assert self.file_.cert_serial_num
            assert self.file_.hash
            # It's not the multi-package itself that is signed.
            assert not packaged.is_signed(self.file_.file_path)
            # It's the internal xpi.
            folder = tempfile.mkdtemp()
            try:
                extract_xpi(self.file_.file_path, folder)
                assert packaged.is_signed(
                    os.path.join(folder, 'random_extension.xpi'))
                # And only the one that is an extension.
                assert not packaged.is_signed(
                    os.path.join(folder, 'random_theme.xpi'))
            finally:
                amo.utils.rm_local_tmp_dir(folder)


class TestTasks(amo.tests.TestCase):

    def setUp(self):
        super(TestTasks, self).setUp()
        self.addon = amo.tests.addon_factory(version_kw={'version': '1.3'})
        self.version = self.addon.current_version
        # Make sure our file/version is at least compatible with FF
        # MIN_NOT_D2C_VERSION.
        self.max_appversion = self.version.apps.first().max
        self.set_max_appversion(settings.MIN_NOT_D2C_VERSION)
        self.file_ = self.version.all_files[0]
        self.file_.update(filename='jetpack.xpi')

    def tearDown(self):
        if os.path.exists(self.get_backup_file_path()):
            os.unlink(self.get_backup_file_path())
        super(TestTasks, self).tearDown()

    def get_backup_file_path(self):
        return u'{0}.backup_signature'.format(self.file_.file_path)

    def set_max_appversion(self, version):
        """Set self.max_appversion to the given version."""
        self.max_appversion.update(version=version,
                                   version_int=version_int(version))

    def assert_backup(self):
        """Make sure there's a backup file."""
        assert os.path.exists(self.get_backup_file_path())

    def assert_no_backup(self):
        """Make sure there's no backup file."""
        assert not os.path.exists(self.get_backup_file_path())

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_bump_version_in_model(self, mock_sign_file):
        # We want to make sure each file has been signed.
        self.file2 = amo.tests.file_factory(version=self.version)
        self.file2.update(filename='jetpack-b.xpi')
        backup_file2_path = u'{0}.backup_signature'.format(
            self.file2.file_path)
        try:
            with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                     self.file_.file_path):
                with amo.tests.copy_file(
                        'apps/files/fixtures/files/jetpack.xpi',
                        self.file2.file_path):
                    file_hash = self.file_.generate_hash()
                    file2_hash = self.file2.generate_hash()
                    assert self.version.version == '1.3'
                    assert self.version.version_int == version_int('1.3')
                    tasks.sign_addons([self.addon.pk])
                    assert mock_sign_file.call_count == 2
                    self.version.reload()
                    assert self.version.version == '1.3.1-signed'
                    assert self.version.version_int == version_int(
                        '1.3.1-signed')
                    assert file_hash != self.file_.generate_hash()
                    assert file2_hash != self.file2.generate_hash()
                    self.assert_backup()
                    assert os.path.exists(backup_file2_path)
        finally:
            if os.path.exists(backup_file2_path):
                os.unlink(backup_file2_path)

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_sign_full(self, mock_sign_file):
        """Use the full signing server if files are fully reviewed."""
        self.file_.update(status=amo.STATUS_PUBLIC)
        with amo.tests.copy_file(
                'apps/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk])
            mock_sign_file.assert_called_with(
                self.file_, settings.SIGNING_SERVER)

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_sign_prelim(self, mock_sign_file):
        """Use the prelim signing server if files aren't fully reviewed."""
        self.file_.update(status=amo.STATUS_LITE)
        with amo.tests.copy_file(
                'apps/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk])
            mock_sign_file.assert_called_with(
                self.file_, settings.PRELIMINARY_SIGNING_SERVER)

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_old_versions(self, mock_sign_file):
        """Don't sign files which are too old, or not default to compatible."""
        def not_signed():
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')

            # Too old, don't sign.
            self.set_max_appversion('1')  # Very very old.
            tasks.sign_addons([self.addon.pk])
            not_signed()

            # MIN_D2C_VERSION, but strict compat: don't sign.
            self.set_max_appversion(settings.MIN_D2C_VERSION)
            self.file_.update(strict_compatibility=True)
            tasks.sign_addons([self.addon.pk])
            not_signed()

            # MIN_D2C_VERSION, but binary component: don't sign.
            self.file_.update(strict_compatibility=False,
                              binary_components=True)
            tasks.sign_addons([self.addon.pk])
            not_signed()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_filename(self, mock_sign_file):
        """Sign files which have non-ascii filenames."""
        self.file_.update(filename=u'jétpack.xpi')
        with amo.tests.copy_file(
                'apps/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'
            assert self.version.version_int == version_int('1.3.1-signed')
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_version(self, mock_sign_file):
        """Sign versions which have non-ascii version numbers."""
        self.version.update(version=u'é1.3')
        with amo.tests.copy_file(
                'apps/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == u'é1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == u'é1.3.1-signed'
            assert self.version.version_int == version_int(u'é1.3.1-signed')
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_sign_bump_old_versions_default_compat(self, mock_sign_file):
        """Sign files which are old, but default to compatible."""
        with amo.tests.copy_file(
                'apps/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            self.set_max_appversion(settings.MIN_D2C_VERSION)
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'
            assert self.version.version_int == version_int('1.3.1-signed')
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_sign_bump_new_versions_not_default_compat(self, mock_sign_file):
        """Sign files which are recent, event if not default to compatible."""
        with amo.tests.copy_file(
                'apps/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            self.file_.update(binary_components=True,
                              strict_compatibility=True)
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'
            assert self.version.version_int == version_int('1.3.1-signed')
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_resign_dont_bump_version_in_model(self, mock_sign_file):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-addon-signature.xpi',
                self.file_.file_path):
            self.file_.update(is_signed=True)
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_version_bad_zipfile(self, mock_sign_file):
        with amo.tests.copy_file(__file__, self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_sign_error(self, mock_sign_file):
        mock_sign_file.side_effect = IOError()
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_dont_bump_not_signed(self, mock_sign_file):
        mock_sign_file.return_value = None  # Pretend we didn't sign.
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('lib.crypto.tasks.sign_file')
    def test_resign_bump_version_in_model_if_force(self, mock_sign_file):
        with amo.tests.copy_file(
                'apps/files/fixtures/files/new-addon-signature.xpi',
                self.file_.file_path):
            self.file_.update(is_signed=True)
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            tasks.sign_addons([self.addon.pk], force=True)
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'
            assert self.version.version_int == version_int('1.3.1-signed')
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

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
