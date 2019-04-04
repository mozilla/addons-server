# -*- coding: utf-8 -*-
import hashlib
import os
import shutil
import zipfile
import collections
import datetime

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.utils.encoding import force_bytes, force_text

import mock
import pytest
import responses
import pytz

from waffle.testutils import override_sample, override_switch

from olympia import amo
from olympia.addons.models import AddonUser
from olympia.amo.tests import TestCase
from olympia.lib.crypto import signing, tasks
from olympia.lib.git import AddonGitRepository
from olympia.versions.compare import version_int
from olympia.lib.tests.test_git import _run_process


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestSigning(TestCase):

    def setUp(self):
        super(TestSigning, self).setUp()

        # Change addon file name
        self.addon = amo.tests.addon_factory()
        self.addon.update(guid='xxxxx')
        self.version = self.addon.current_version
        self.file_ = self.version.all_files[0]

        # Add actual file to addons
        if not os.path.exists(os.path.dirname(self.file_.file_path)):
            os.makedirs(os.path.dirname(self.file_.file_path))

        fp = zipfile.ZipFile(self.file_.file_path, 'w')
        fp.writestr('install.rdf', (
            '<?xml version="1.0"?><RDF '
            '   xmlns="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            '   xmlns:em="http://www.mozilla.org/2004/em-rdf#">'
            '<Description about="urn:mozilla:install-manifest">'
            '      <em:id>foo@jetpack</em:id>'
            '      <em:type>2</em:type>'
            '      <em:bootstrap>true</em:bootstrap>'
            '      <em:unpack>false</em:unpack>'
            '      <em:version>0.1</em:version>'
            '      <em:name>foo</em:name>'
            '      <em:description>foo bar</em:description>'
            '      <em:optionsType>2</em:optionsType>'
            '      <em:targetApplication></em:targetApplication>'
            '</Description>'
            '</RDF>'))

        fp.close()

        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

    def tearDown(self):
        if os.path.exists(self.file_.file_path):
            os.unlink(self.file_.file_path)
        if os.path.exists(self.file_.guarded_file_path):
            os.unlink(self.file_.guarded_file_path)
        super(TestSigning, self).tearDown()

    def _sign_file(self, file_):
        signing.sign_file(file_)

    def _get_signature_details(self):
        with zipfile.ZipFile(self.file_.current_file_path, mode='r') as zobj:
            info = signing.SignatureInfo(zobj.read('META-INF/mozilla.rsa'))
            manifest = force_text(zobj.read('META-INF/manifest.mf'))
            return info, manifest

    def assert_not_signed(self):
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        assert not signing.is_signed(self.file_.file_path)

    def assert_signed(self):
        assert self.file_.is_signed
        assert self.file_.cert_serial_num
        assert self.file_.hash
        assert signing.is_signed(self.file_.file_path)

    def test_supports_firefox_old_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and not default to compatible.
        max_appversion.update(version='4', version_int=version_int('4'))
        self.file_.update(binary_components=True, strict_compatibility=True)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_android_old_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and not default to compatible.
        max_appversion.update(application=amo.ANDROID.id,
                              version='4', version_int=version_int('4'))
        self.file_.update(binary_components=True, strict_compatibility=True)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_old_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and default to compatible.
        max_appversion.update(version='4', version_int=version_int('4'))
        self.file_.update(binary_components=False, strict_compatibility=False)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_android_old_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and default to compatible.
        max_appversion.update(application=amo.ANDROID.id,
                              version='4', version_int=version_int('4'))
        self.file_.update(binary_components=False, strict_compatibility=False)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_recent_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Recent, default to compatible.
        max_appversion.update(version='37', version_int=version_int('37'))
        self.file_.update(binary_components=False, strict_compatibility=False)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_android_recent_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Recent, not default to compatible.
        max_appversion.update(application=amo.ANDROID.id,
                              version='37', version_int=version_int('37'))
        self.file_.update(binary_components=True, strict_compatibility=True)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_sign_file(self):
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()
        # Make sure there's two newlines at the end of the mozilla.sf file (see
        # bug 1158938).
        with zipfile.ZipFile(self.file_.file_path, mode='r') as zf:
            with zf.open('META-INF/mozilla.sf', 'r') as mozillasf:
                assert mozillasf.read().endswith(b'\n\n')

    def test_sign_file_non_ascii_filename(self):
        src = self.file_.file_path
        self.file_.update(filename=u'jétpack.xpi')
        shutil.move(src, self.file_.file_path)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_sign_file_with_utf8_filename_inside_package(self):
        fpath = 'src/olympia/files/fixtures/files/unicode-filenames.xpi'
        with amo.tests.copy_file(fpath, self.file_.file_path, overwrite=True):
            self.assert_not_signed()
            signing.sign_file(self.file_)
            self.assert_signed()

            with zipfile.ZipFile(self.file_.file_path, mode='r') as zf:
                with zf.open('META-INF/manifest.mf', 'r') as manifest_mf:
                    manifest_contents = manifest_mf.read().decode('utf-8')
                    assert u'\u1109\u1161\u11a9' in manifest_contents

    def test_no_sign_missing_file(self):
        os.unlink(self.file_.file_path)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        with self.assertRaises(signing.SigningError):
            signing.sign_file(self.file_)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        assert not signing.is_signed(self.file_.file_path)

    def test_dont_sign_search_plugins(self):
        self.addon.update(type=amo.ADDON_SEARCH)
        self.file_.update(is_webextension=False)
        signing.sign_file(self.file_)
        self.assert_not_signed()

    def test_dont_sign_again_mozilla_signed_extensions(self):
        """Don't try to resign mozilla signed extensions."""
        self.file_.update(is_mozilla_signed_extension=True)
        signing.sign_file(self.file_)
        self.assert_not_signed()

    def test_is_signed(self):
        assert not signing.is_signed(self.file_.file_path)
        signing.sign_file(self.file_)
        assert signing.is_signed(self.file_.file_path)

    def test_size_updated(self):
        unsigned_size = storage.size(self.file_.file_path)
        signing.sign_file(self.file_)
        signed_size = storage.size(self.file_.file_path)
        assert self.file_.size == signed_size
        assert unsigned_size < signed_size

    def test_call_signing(self):
        assert signing.sign_file(self.file_)

        signature_info, manifest = self._get_signature_details()

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest == (
            'Manifest-Version: 1.0\n\n'
            'Name: install.rdf\n'
            'Digest-Algorithms: MD5 SHA1 SHA256\n'
            'MD5-Digest: AtjchjiOU/jDRLwMx214hQ==\n'
            'SHA1-Digest: W9kwfZrvMkbgjOx6nDdibCNuCjk=\n'
            'SHA256-Digest: 3Wjjho1pKD/9VaK+FszzvZFN/2crBmaWbdisLovwo6g=\n\n'
        )

    def test_call_signing_on_file_in_guarded_file_path(self):
        # We should be able to sign files even if the associated File instance
        # or the add-on is disabled.
        # First let's disable the file and prove that we're only dealing with
        # the file in guarded add-ons storage.
        assert not os.path.exists(self.file_.guarded_file_path)
        assert os.path.exists(self.file_.file_path)
        self.file_.update(status=amo.STATUS_DISABLED)
        assert os.path.exists(self.file_.guarded_file_path)
        assert not os.path.exists(self.file_.file_path)

        # Then call the signing test as normal.
        self.test_call_signing()

    def test_call_signing_too_long_guid_bug_1203365(self):
        long_guid = 'x' * 65
        hashed = hashlib.sha256(force_bytes(long_guid)).hexdigest()
        self.addon.update(guid=long_guid)
        signing.sign_file(self.file_)

        signature_info, manifest = self._get_signature_details()

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == hashed
        assert manifest == (
            'Manifest-Version: 1.0\n\n'
            'Name: install.rdf\n'
            'Digest-Algorithms: MD5 SHA1 SHA256\n'
            'MD5-Digest: AtjchjiOU/jDRLwMx214hQ==\n'
            'SHA1-Digest: W9kwfZrvMkbgjOx6nDdibCNuCjk=\n'
            'SHA256-Digest: 3Wjjho1pKD/9VaK+FszzvZFN/2crBmaWbdisLovwo6g=\n\n'
        )

    def test_get_id_short_guid(self):
        assert len(self.addon.guid) <= 64
        assert len(signing.get_id(self.addon)) <= 64
        assert signing.get_id(self.addon) == self.addon.guid

    def test_get_id_longest_allowed_guid_bug_1203365(self):
        long_guid = 'x' * 64
        self.addon.update(guid=long_guid)
        assert signing.get_id(self.addon) == self.addon.guid

    def test_get_id_long_guid_bug_1203365(self):
        long_guid = u'x' * 65
        hashed = hashlib.sha256(force_bytes(long_guid)).hexdigest()
        self.addon.update(guid=long_guid)
        assert len(self.addon.guid) > 64
        assert len(signing.get_id(self.addon)) <= 64
        assert signing.get_id(self.addon) == hashed

    def test_sign_addon_with_unicode_guid(self):
        self.addon.update(guid=u'NavratnePeniaze@NávratnéPeniaze')

        signing.sign_file(self.file_)

        signature_info, manifest = self._get_signature_details()

        subject_info = signature_info.signer_certificate['subject']

        assert (
            subject_info['common_name'] ==
            u'NavratnePeniaze@NávratnéPeniaze')
        assert manifest == (
            'Manifest-Version: 1.0\n\n'
            'Name: install.rdf\n'
            'Digest-Algorithms: MD5 SHA1 SHA256\n'
            'MD5-Digest: AtjchjiOU/jDRLwMx214hQ==\n'
            'SHA1-Digest: W9kwfZrvMkbgjOx6nDdibCNuCjk=\n'
            'SHA256-Digest: 3Wjjho1pKD/9VaK+FszzvZFN/2crBmaWbdisLovwo6g=\n\n')

    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_runs_git_extraction_after_signing(self):
        # Make sure the initial version is already extracted, simulating
        # a regular upload.
        AddonGitRepository.extract_and_commit_from_version(self.version)
        self.version.refresh_from_db()

        old_git_hash = self.version.git_hash

        signing.sign_file(self.file_)

        self.version.refresh_from_db()
        assert self.version.git_hash != old_git_hash

        repo = AddonGitRepository(self.addon)

        output = _run_process('git log listed', repo)
        assert output.count('Create new version') == 2
        assert '(after successful signing)' in output

        # 2 actual commits, including the repo initialization
        assert output.count('Mozilla Add-ons Robot') == 3


@override_settings(ENABLE_ADDON_SIGNING=True)
@override_sample('activate-autograph-file-signing', active=True)
class TestSigningNewFileEndpoint(TestSigning):

    def test_call_signing(self):
        assert signing.sign_file(self.file_)

        signature_info, manifest = self._get_signature_details()

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 3
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: install.rdf\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: W9kwfZrvMkbgjOx6nDdibCNuCjk=\n'
            'SHA256-Digest: 3Wjjho1pKD/9VaK+FszzvZFN/2crBmaWbdisLovwo6g=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: yguu1oY209BnHZkqftJFZb8UANQ=\n'
            'SHA256-Digest: BJOnqdLGdmNsM6ZE2FRFOrEUFQd2AYRlg9U/+ETXUgM=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
        )

    def test_sign_addon_with_unicode_guid(self):
        self.addon.update(guid=u'NavratnePeniaze@NávratnéPeniaze')

        signing.sign_file(self.file_)

        signature_info, manifest = self._get_signature_details()

        subject_info = signature_info.signer_certificate['subject']

        assert (
            subject_info['common_name'] ==
            u'NavratnePeniaze@NávratnéPeniaze')
        assert manifest.count('Name: ') == 3
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: install.rdf\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: W9kwfZrvMkbgjOx6nDdibCNuCjk=\n'
            'SHA256-Digest: 3Wjjho1pKD/9VaK+FszzvZFN/2crBmaWbdisLovwo6g=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: yguu1oY209BnHZkqftJFZb8UANQ=\n'
            'SHA256-Digest: BJOnqdLGdmNsM6ZE2FRFOrEUFQd2AYRlg9U/+ETXUgM=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
        )

    def test_call_signing_too_long_guid_bug_1203365(self):
        long_guid = 'x' * 65
        hashed = hashlib.sha256(force_bytes(long_guid)).hexdigest()
        self.addon.update(guid=long_guid)
        signing.sign_file(self.file_)

        signature_info, manifest = self._get_signature_details()

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == hashed
        assert manifest.count('Name: ') == 3
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: install.rdf\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: W9kwfZrvMkbgjOx6nDdibCNuCjk=\n'
            'SHA256-Digest: 3Wjjho1pKD/9VaK+FszzvZFN/2crBmaWbdisLovwo6g=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: yguu1oY209BnHZkqftJFZb8UANQ=\n'
            'SHA256-Digest: BJOnqdLGdmNsM6ZE2FRFOrEUFQd2AYRlg9U/+ETXUgM=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
        )


class TestTasks(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestTasks, self).setUp()
        self.addon = amo.tests.addon_factory(version_kw={'version': '1.3'})
        self.version = self.addon.current_version
        # Make sure our file/version is at least compatible with FF
        # '37'.
        self.max_appversion = self.version.apps.first().max
        self.set_max_appversion('37')
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_no_bump_unreviewed(self, mock_sign_file):
        """Don't bump nor sign unreviewed files."""
        for status in amo.UNREVIEWED_FILE_STATUSES:
            self.file_.update(status=status)
            fpath = 'src/olympia/files/fixtures/files/jetpack.xpi'
            with amo.tests.copy_file(fpath, self.file_.file_path):
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_bump_version_in_model(self, mock_sign_file):
        # We want to make sure each file has been signed.
        self.file2 = amo.tests.file_factory(version=self.version)
        self.file2.update(filename='jetpack-b.xpi')
        backup_file2_path = u'{0}.backup_signature'.format(
            self.file2.file_path)
        try:
            fpath = 'src/olympia/files/fixtures/files/jetpack.xpi'
            with amo.tests.copy_file(fpath, self.file_.file_path):
                with amo.tests.copy_file(
                        'src/olympia/files/fixtures/files/jetpack.xpi',
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_full(self, mock_sign_file):
        """Use the signing server if files are approved."""
        self.file_.update(status=amo.STATUS_PUBLIC)
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk])
            mock_sign_file.assert_called_with(self.file_)

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_supported_applications(self, mock_sign_file):
        """Make sure we sign for all supported applications."""
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            for app in (amo.ANDROID.id, amo.FIREFOX.id):
                self.max_appversion.update(application=app)
                tasks.sign_addons([self.addon.pk])
                mock_sign_file.assert_called_with(self.file_)
                mock_sign_file.reset_mock()

    def assert_not_signed(self, mock_sign_file, file_hash):
        assert not mock_sign_file.called
        self.version.reload()
        assert self.version.version == '1.3'
        assert self.version.version_int == version_int('1.3')
        assert file_hash == self.file_.generate_hash()
        self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_other_applications(self, mock_sign_file):
        """Don't sign files which are for applications we don't sign for."""
        path = 'src/olympia/files/fixtures/files/jetpack.xpi'
        with amo.tests.copy_file(path, self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')

            apps_without_signing = [app for app in amo.APPS_ALL.keys()
                                    if app not in signing.SIGN_FOR_APPS]

            for app in apps_without_signing:
                self.max_appversion.update(application=app)
                tasks.sign_addons([self.addon.pk])
                self.assert_not_signed(mock_sign_file, file_hash)

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_filename(self, mock_sign_file):
        """Sign files which have non-ascii filenames."""
        self.file_.update(filename=u'jétpack.xpi')
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_version(self, mock_sign_file):
        """Sign versions which have non-ascii version numbers."""
        self.version.update(version=u'é1.3')
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_old_versions_default_compat(self, mock_sign_file):
        """Sign files which are old, but default to compatible."""
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '1.3'
            assert self.version.version_int == version_int('1.3')
            self.set_max_appversion('4')
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '1.3.1-signed'
            assert self.version.version_int == version_int('1.3.1-signed')
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_new_versions_not_default_compat(self, mock_sign_file):
        """Sign files which are recent, event if not default to compatible."""
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_resign_dont_bump_version_in_model(self, mock_sign_file):
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/new-addon-signature.xpi',
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_sign_error(self, mock_sign_file):
        mock_sign_file.side_effect = IOError()
        fpath = 'src/olympia/files/fixtures/files/jetpack.xpi'
        with amo.tests.copy_file(fpath, self.file_.file_path):
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_bump_not_signed(self, mock_sign_file):
        mock_sign_file.return_value = None  # Pretend we didn't sign.
        fpath = 'src/olympia/files/fixtures/files/jetpack.xpi'
        with amo.tests.copy_file(fpath, self.file_.file_path):
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_resign_bump_version_in_model_if_force(self, mock_sign_file):
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/new-addon-signature.xpi',
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

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_mail(self, mock_sign_file):
        """Check that an email reason can be provided."""
        self.file_.update(status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=self.addon, user_id=999)
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/jetpack.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk], reason='expiry')
            mock_sign_file.assert_called_with(self.file_)

        assert 'expiration' in mail.outbox[0].message().as_string()


@pytest.mark.parametrize(('old', 'new'), [
    ('1.1', '1.1.1-signed'),
    ('1.1.1-signed.1', '1.1.1-signed.1.1-signed'),
    ('1.1.1-signed', '1.1.1-signed-2'),
    ('1.1.1-signed-3', '1.1.1-signed-4'),
    ('1.1.1-signed.1-signed-16', '1.1.1-signed.1-signed-17')
])
def test_get_new_version_number(old, new):
    assert tasks.get_new_version_number(old) == new


class TestSignatureInfo(object):

    @pytest.fixture(autouse=True)
    def setup(self):
        fixture_path = (
            'src/olympia/lib/crypto/tests/'
            'mozilla-generated-by-openssl.pkcs7.der')

        with open(fixture_path, 'rb') as fobj:
            self.pkcs7 = fobj.read()

        self.info = signing.SignatureInfo(self.pkcs7)

    def test_loading_reading_string(self):
        info = signing.SignatureInfo(self.pkcs7)
        assert isinstance(info.content, collections.OrderedDict)

    def test_loading_pass_signature_info_instance(self):
        info = signing.SignatureInfo(self.pkcs7)
        assert isinstance(info.content, collections.OrderedDict)

        info2 = signing.SignatureInfo(info)

        assert isinstance(info2.content, collections.OrderedDict)
        assert info2.content == info.content

    def test_signer_serial_number(self):
        assert self.info.signer_serial_number == 1498181554500

    def test_issuer(self):
        assert self.info.issuer == collections.OrderedDict([
            ('country_name', 'US'),
            ('state_or_province_name', 'CA'),
            ('locality_name', 'Mountain View'),
            ('organization_name', 'Addons Test Signing'),
            ('common_name', 'test.addons.signing.root.ca'),
            ('email_address', 'opsec+stagerootaddons@mozilla.com')
        ])

    def test_signer_certificate(self):
        assert (
            self.info.signer_certificate['serial_number'] ==
            self.info.signer_serial_number)
        assert (
            self.info.signer_certificate['issuer'] ==
            self.info.issuer)

        expected = collections.OrderedDict([
            ('version', 'v3'),
            ('serial_number', 1498181554500),
            ('signature', collections.OrderedDict([
                ('algorithm', 'sha256_rsa'), ('parameters', None)])),
            ('issuer', collections.OrderedDict([
                ('country_name', 'US'),
                ('state_or_province_name', 'CA'),
                ('locality_name', 'Mountain View'),
                ('organization_name', 'Addons Test Signing'),
                ('common_name', 'test.addons.signing.root.ca'),
                ('email_address', 'opsec+stagerootaddons@mozilla.com')])),
            ('validity', collections.OrderedDict([
                ('not_before', datetime.datetime(
                    2017, 6, 23, 1, 32, 34, tzinfo=pytz.utc)),
                ('not_after', datetime.datetime(
                    2027, 6, 21, 1, 32, 34, tzinfo=pytz.utc))])),
            ('subject', collections.OrderedDict([
                ('organizational_unit_name', 'Testing'),
                ('country_name', 'US'),
                ('locality_name', 'Mountain View'),
                ('organization_name', 'Addons Testing'),
                ('state_or_province_name', 'CA'),
                ('common_name', '{02b860db-e71f-48d2-a5a0-82072a93d33c}')])),
            ('subject_public_key_info', collections.OrderedDict([
                ('algorithm', collections.OrderedDict([
                    ('algorithm', 'rsa'),
                    ('parameters', None)])),
                ('public_key', collections.OrderedDict([
                    ('modulus', int(
                        '85289209018591781267198931558814435907521407777661'
                        '50749316736213617395458578680335589192171418852036'
                        '79278813048882998104120530700223207250951695884439'
                        '20772452388935409377024686932620042402964287828106'
                        '51257320080972660594945900464995547687116064792520'
                        '10385231846333656801523388692257373069803424678966'
                        '83558316878945090150671487395382420988138292553386'
                        '65273893489909596214808207811839117255018821125538'
                        '88010045768747055709235990054867405484806043609964'
                        '46844151945633093802308152276459710592644539761011'
                        '95743982561110649516741370965629194907895538590306'
                        '29899529219665410153860752870947521013079820756069'
                        '47104737107240593827799410733495909560358275915879'
                        '55064950558358425436354620230911526069861662920050'
                        '43124539276872288437450042840027281372269967539939'
                        '24111213120065958637042429018593980801963496240784'
                        '12170983502746046961830237201163411151902047596357'
                        '52875610569157058411595354595985036610666909234931'
                        '24897289875099542550941258245633054592232417696315'
                        '40182071794766323211615139265042704991415186206585'
                        '75885408887756385761663648099801365729955339334103'
                        '60468108188015261735738849468668895508239573547213'
                        '28312488126574859733988724870493942605656816541143'
                        '61628373225003401044258905283594542783785817504173'
                        '841847040037917474056678747905247')),
                    ('public_exponent', 65537)]))])),
            ('issuer_unique_id', None),
            ('subject_unique_id', None),
            ('extensions', None)])

        assert self.info.signer_certificate == expected
