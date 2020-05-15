# -*- coding: utf-8 -*-
import hashlib
import os
import shutil
import zipfile
import collections
import datetime
import json

from django.db import transaction
from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.test.testcases import TransactionTestCase
from django.utils.encoding import force_bytes, force_text

from unittest import mock
import pytest
import responses
import pytz

from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.models import AddonUser
from olympia.amo.tests import TestCase
from olympia.discovery.models import DiscoveryItem
from olympia.lib.crypto import signing, tasks
from olympia.git.utils import AddonGitRepository
from olympia.git.tests.test_utils import _run_process
from olympia.versions.compare import version_int


def _get_signature_details(path):
    with zipfile.ZipFile(path, mode='r') as zobj:
        info = signing.SignatureInfo(zobj.read('META-INF/mozilla.rsa'))
        manifest = force_text(zobj.read('META-INF/manifest.mf'))
        return info, manifest


def _get_recommendation_data(path):
    with zipfile.ZipFile(path, mode='r') as zobj:
        return json.loads(force_text(zobj.read('mozilla-recommendation.json')))


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestSigning(TestCase):

    def setUp(self):
        super().setUp()

        # Change addon file name
        self.addon = amo.tests.addon_factory(file_kw={
            'filename': 'webextension.xpi'
        })
        self.addon.update(guid='xxxxx')
        self.version = self.addon.current_version
        self.file_ = self.version.all_files[0]

        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

    def tearDown(self):
        if os.path.exists(self.file_.file_path):
            os.unlink(self.file_.file_path)
        if os.path.exists(self.file_.guarded_file_path):
            os.unlink(self.file_.guarded_file_path)
        super().tearDown()

    def _sign_file(self, file_):
        signing.sign_file(file_)

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

        signature_info, manifest = _get_signature_details(
            self.file_.current_file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: index.js\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: nsBG7x6peXmndngU43AGIi6CKBM=\n'
            'SHA256-Digest: Hh3yviccEoUvKvoYupqPO+k900wpIMgPFsRMmRW+fGg=\n\n'
            'Name: manifest.json\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: +1L0sNk03EPxDOB6QX3QbtFy8XA=\n'
            'SHA256-Digest: a+UZOkXfCnXKTRM459ip/0OdJt9SxM/DAOkhKTyCsSA=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: xy12EQlU8eCap0SY5C0WMHoNtj8=\n'
            'SHA256-Digest: YdsmjrtOMGyISHs7UgxAXzLHSKoQRGe+NGzc4pDCos8=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
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

        signature_info, manifest = _get_signature_details(
            self.file_.current_file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == hashed
        assert manifest.count('Name: ') == 4
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: index.js\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: nsBG7x6peXmndngU43AGIi6CKBM=\n'
            'SHA256-Digest: Hh3yviccEoUvKvoYupqPO+k900wpIMgPFsRMmRW+fGg=\n\n'
            'Name: manifest.json\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: +1L0sNk03EPxDOB6QX3QbtFy8XA=\n'
            'SHA256-Digest: a+UZOkXfCnXKTRM459ip/0OdJt9SxM/DAOkhKTyCsSA=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: xy12EQlU8eCap0SY5C0WMHoNtj8=\n'
            'SHA256-Digest: YdsmjrtOMGyISHs7UgxAXzLHSKoQRGe+NGzc4pDCos8=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
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

        signature_info, manifest = _get_signature_details(
            self.file_.current_file_path)

        subject_info = signature_info.signer_certificate['subject']

        assert (
            subject_info['common_name'] ==
            u'NavratnePeniaze@NávratnéPeniaze')
        assert manifest.count('Name: ') == 4
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: index.js\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: nsBG7x6peXmndngU43AGIi6CKBM=\n'
            'SHA256-Digest: Hh3yviccEoUvKvoYupqPO+k900wpIMgPFsRMmRW+fGg=\n\n'
            'Name: manifest.json\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: +1L0sNk03EPxDOB6QX3QbtFy8XA=\n'
            'SHA256-Digest: a+UZOkXfCnXKTRM459ip/0OdJt9SxM/DAOkhKTyCsSA=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: xy12EQlU8eCap0SY5C0WMHoNtj8=\n'
            'SHA256-Digest: YdsmjrtOMGyISHs7UgxAXzLHSKoQRGe+NGzc4pDCos8=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
        )

    def test_call_signing_recommended(self):
        # This is the usual process for recommended add-ons, they're
        # in "pending recommendation" and only *after* we approve and sign
        # them they will become "recommended". Once the `recommendable`
        # flag is turned off we won't sign further versions as recommended.
        DiscoveryItem.objects.create(
            addon=self.file_.version.addon,
            recommendable=True)

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(
            self.file_.current_file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 5

        assert 'Name: mozilla-recommendation.json' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest

        recommendation_data = _get_recommendation_data(
            self.file_.current_file_path)
        assert recommendation_data['addon_id'] == 'xxxxx'
        assert recommendation_data['states'] == ['recommended']

    def test_call_signing_recommendable_unlisted(self):
        # Unlisted versions, even when the add-on is recommendable, should
        # never be recommended.
        DiscoveryItem.objects.create(
            addon=self.file_.version.addon,
            recommendable=True)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(
            self.file_.current_file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4

        assert 'Name: mozilla-recommendation.json' not in manifest

    def test_call_signing_not_recommendable(self):
        DiscoveryItem.objects.create(
            addon=self.file_.version.addon,
            recommendable=False)

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(
            self.file_.current_file_path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4

        assert 'Name: mozilla-recommendation.json' not in manifest


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestTransactionRelatedSigning(TransactionTestCase):

    def setUp(self):
        super().setUp()

        self.addon = amo.tests.addon_factory(file_kw={
            'filename': 'webextension.xpi'
        })
        self.version = self.addon.current_version

        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

        # Make sure the initial version is already extracted, simulating
        # a regular upload.
        AddonGitRepository.extract_and_commit_from_version(self.version)
        self.version.refresh_from_db()

    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_runs_git_extraction_after_signing(self):
        old_git_hash = self.version.git_hash

        with transaction.atomic():
            signing.sign_file(self.version.current_file)

        self.version.refresh_from_db()
        assert self.version.git_hash != old_git_hash

        repo = AddonGitRepository(self.addon)

        output = _run_process('git log listed', repo)
        assert output.count('Create new version') == 2
        assert '(after successful signing)' in output

        # 2 actual commits, including the repo initialization
        assert output.count('Mozilla Add-ons Robot') == 3

    @mock.patch('olympia.versions.tasks.extract_version_to_git.delay')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_commits_to_git_async_signing_happened(self, extract_mock):
        old_git_hash = self.version.git_hash

        def call_sign_file():
            signing.sign_file(self.version.current_file)
            # raise ValueError after the sign_file call so that
            # the extraction is queued via the on_commit hook
            # but the atomic block won't complete.
            raise ValueError()

        with pytest.raises(ValueError):
            with transaction.atomic():
                call_sign_file()

        extract_mock.assert_not_called()

        self.version.refresh_from_db()
        assert self.version.git_hash == old_git_hash

        repo = AddonGitRepository(self.addon)

        output = _run_process('git log listed', repo)
        assert output.count('Create new version') == 1


class TestTasks(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestTasks, self).setUp()
        self.addon = amo.tests.addon_factory(
            name=u'Rændom add-on',
            version_kw={'version': '0.0.1'})
        self.version = self.addon.current_version
        self.max_appversion = self.version.apps.first().max
        self.set_max_appversion('48')
        self.file_ = self.version.all_files[0]
        self.file_.update(filename='webextension.xpi')

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
            fpath = 'src/olympia/files/fixtures/files/webextension.xpi'
            with amo.tests.copy_file(fpath, self.file_.file_path):
                file_hash = self.file_.generate_hash()
                assert self.version.version == '0.0.1'
                tasks.sign_addons([self.addon.pk])
                assert not mock_sign_file.called
                self.version.reload()
                assert self.version.version == '0.0.1'
                assert file_hash == self.file_.generate_hash()
                self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_bump_version_in_model(self, mock_sign_file):
        # We want to make sure each file has been signed.
        self.file2 = amo.tests.file_factory(version=self.version)
        self.file2.update(filename='webextension-b.xpi')
        backup_file2_path = u'{0}.backup_signature'.format(
            self.file2.file_path)
        try:
            fpath = 'src/olympia/files/fixtures/files/webextension.xpi'
            with amo.tests.copy_file(fpath, self.file_.file_path):
                with amo.tests.copy_file(
                        'src/olympia/files/fixtures/files/webextension.xpi',
                        self.file2.file_path):
                    file_hash = self.file_.generate_hash()
                    file2_hash = self.file2.generate_hash()
                    assert self.version.version == '0.0.1'
                    tasks.sign_addons([self.addon.pk])
                    assert mock_sign_file.call_count == 2
                    self.version.reload()
                    assert self.version.version == '0.0.1.1-signed'
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
        self.file_.update(status=amo.STATUS_APPROVED)
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/webextension.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk])
            mock_sign_file.assert_called_with(self.file_)

    def assert_not_signed(self, mock_sign_file, file_hash):
        assert not mock_sign_file.called
        self.version.reload()
        assert self.version.version == '0.0.1'
        assert file_hash == self.file_.generate_hash()
        self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_filename(self, mock_sign_file):
        """Sign files which have non-ascii filenames."""
        self.file_.update(filename=u'wébextension.xpi')
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/webextension.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1.1-signed'
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_version(self, mock_sign_file):
        """Sign versions which have non-ascii version numbers."""
        self.version.update(version=u'é0.0.1')
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/webextension.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == u'é0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == u'é0.0.1.1-signed'
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_old_versions_default_compat(self, mock_sign_file):
        """Sign files which are old, but default to compatible."""
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/webextension.xpi',
                self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            self.set_max_appversion('4')
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1.1-signed'
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_resign_and_bump_version_in_model(self, mock_sign_file):
        fname = (
            './src/olympia/files/fixtures/files/webextension_signed_already'
            '.xpi')
        with amo.tests.copy_file(fname, self.file_.file_path):
            self.file_.update(is_signed=True)
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1.1-signed'
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_version_bad_zipfile(self, mock_sign_file):
        with amo.tests.copy_file(__file__, self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1'
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_sign_error(self, mock_sign_file):
        mock_sign_file.side_effect = IOError()
        fpath = 'src/olympia/files/fixtures/files/webextension.xpi'
        with amo.tests.copy_file(fpath, self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1'
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_bump_not_signed(self, mock_sign_file):
        mock_sign_file.return_value = None  # Pretend we didn't sign.
        fpath = 'src/olympia/files/fixtures/files/webextension.xpi'
        with amo.tests.copy_file(fpath, self.file_.file_path):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1'
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_resign_only_current_versions(self, mock_sign_file):
        fname = './src/olympia/files/fixtures/files/webextension.xpi'

        new_current_version = amo.tests.version_factory(
            addon=self.addon, version='0.0.2')
        new_file = new_current_version.current_file

        with amo.tests.copy_file(fname, new_file.file_path):
            with amo.tests.copy_file(fname, self.file_.file_path):
                file_hash = self.file_.generate_hash()
                new_file_hash = new_file.generate_hash()

                tasks.sign_addons([self.addon.pk])

                # Only one signing call since we only sign the most recent
                # versions
                assert mock_sign_file.call_count == 1

                new_current_version.reload()
                assert new_current_version.version == '0.0.2.1-signed'
                assert new_file_hash != new_file.generate_hash()

                # Verify that the old version hasn't been resigned
                self.version.reload()
                assert self.version.version == '0.0.1'
                assert file_hash == self.file_.generate_hash()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_mail_cose_subject(self, mock_sign_file):
        self.file_.update(status=amo.STATUS_APPROVED)
        AddonUser.objects.create(addon=self.addon, user_id=999)
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/webextension.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk])
            mock_sign_file.assert_called_with(self.file_)

        assert 'stronger signature' in mail.outbox[0].message().as_string()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_mail_cose_message_contains_addon_name(self, mock_sign_file):
        self.file_.update(status=amo.STATUS_APPROVED)
        AddonUser.objects.create(addon=self.addon, user_id=999)
        with amo.tests.copy_file(
                'src/olympia/files/fixtures/files/webextension.xpi',
                self.file_.file_path):
            tasks.sign_addons([self.addon.pk])
            mock_sign_file.assert_called_with(self.file_)

        assert u'Rændom add-on' in mail.outbox[0].message().as_string()


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
