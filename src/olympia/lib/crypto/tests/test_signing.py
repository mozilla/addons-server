import collections
import datetime
import hashlib
import io
import json
import os
import zipfile

from django.db import transaction
from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.test.testcases import TransactionTestCase
from django.utils.encoding import force_bytes, force_str

from unittest import mock
import pytest
import responses
import pytz

from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.models import AddonUser
from olympia.amo.tests import addon_factory, TestCase, version_factory
from olympia.constants.promoted import LINE, RECOMMENDED, SPOTLIGHT
from olympia.lib.crypto import signing, tasks
from olympia.versions.compare import version_int


def _get_signature_details(path):
    with zipfile.ZipFile(path, mode='r') as zobj:
        info = signing.SignatureInfo(zobj.read('META-INF/mozilla.rsa'))
        manifest = force_str(zobj.read('META-INF/manifest.mf'))
        return info, manifest


def _get_recommendation_data(path):
    with zipfile.ZipFile(path, mode='r') as zobj:
        return json.loads(force_str(zobj.read('mozilla-recommendation.json')))


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestSigning(TestCase):
    def setUp(self):
        super().setUp()

        # Change addon file name
        self.addon = addon_factory(
            guid='xxxxx', file_kw={'filename': 'webextension.xpi'}
        )
        self.version = self.addon.current_version
        self.file_ = self.version.file

        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

    def _sign_file(self, file_):
        signing.sign_file(file_)

    def assert_not_signed(self):
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        assert not signing.is_signed(self.file_.file.path)

    def assert_signed(self):
        assert self.file_.is_signed
        assert self.file_.cert_serial_num
        assert self.file_.hash
        assert signing.is_signed(self.file_.file.path)

    def test_supports_firefox_old_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and not default to compatible.
        max_appversion.update(version='4', version_int=version_int('4'))
        self.file_.update(strict_compatibility=True)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_android_old_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and not default to compatible.
        max_appversion.update(
            application=amo.ANDROID.id, version='4', version_int=version_int('4')
        )
        self.file_.update(strict_compatibility=True)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_old_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and default to compatible.
        max_appversion.update(version='4', version_int=version_int('4'))
        self.file_.update(strict_compatibility=False)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_android_old_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Old, and default to compatible.
        max_appversion.update(
            application=amo.ANDROID.id, version='4', version_int=version_int('4')
        )
        self.file_.update(strict_compatibility=False)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_recent_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Recent, default to compatible.
        max_appversion.update(version='37', version_int=version_int('37'))
        self.file_.update(strict_compatibility=False)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_supports_firefox_android_recent_not_default_to_compatible(self):
        max_appversion = self.version.apps.first().max

        # Recent, not default to compatible.
        max_appversion.update(
            application=amo.ANDROID.id, version='37', version_int=version_int('37')
        )
        self.file_.update(strict_compatibility=True)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_sign_file(self):
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()
        # Make sure there's two newlines at the end of the mozilla.sf file (see
        # bug 1158938).
        with zipfile.ZipFile(self.file_.file.path, mode='r') as zf:
            with zf.open('META-INF/mozilla.sf', 'r') as mozillasf:
                assert mozillasf.read().endswith(b'\n\n')

    def test_sign_file_non_ascii_filename(self):
        # Pretend file on filesystem contains non-ascii characters. The
        # upload_to callback won't let us, so emulate what it does - as long as
        # we can read the file afterwards details don't matter.
        old_file_path = self.file_.file.path
        old_file_dirs = os.path.dirname(self.file_.file.name)
        self.file_.file.name = os.path.join(old_file_dirs, 'wébextension.zip')
        os.rename(old_file_path, self.file_.file.path)
        self.assert_not_signed()
        signing.sign_file(self.file_)
        self.assert_signed()

    def test_sign_file_with_utf8_filename_inside_package(self):
        fpath = 'src/olympia/files/fixtures/files/unicode-filenames.xpi'
        with amo.tests.copy_file(fpath, self.file_.file.path, overwrite=True):
            self.assert_not_signed()
            signing.sign_file(self.file_)
            self.assert_signed()

            with zipfile.ZipFile(self.file_.file.path, mode='r') as zf:
                with zf.open('META-INF/manifest.mf', 'r') as manifest_mf:
                    manifest_contents = manifest_mf.read().decode('utf-8')
                    assert '\u1109\u1161\u11a9' in manifest_contents

    def test_no_sign_missing_file(self):
        os.unlink(self.file_.file.path)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        with self.assertRaises(signing.SigningError):
            signing.sign_file(self.file_)
        assert not self.file_.is_signed
        assert not self.file_.cert_serial_num
        assert not self.file_.hash
        assert not signing.is_signed(self.file_.file.path)

    def test_dont_sign_again_mozilla_signed_extensions(self):
        """Don't try to resign mozilla signed extensions."""
        self.file_.update(is_mozilla_signed_extension=True)
        signing.sign_file(self.file_)
        self.assert_not_signed()

    def test_is_signed(self):
        assert not signing.is_signed(self.file_.file.path)
        signing.sign_file(self.file_)
        assert signing.is_signed(self.file_.file.path)

    def test_size_updated(self):
        unsigned_size = storage.size(self.file_.file.path)
        signing.sign_file(self.file_)
        signed_size = storage.size(self.file_.file.path)
        assert self.file_.size == signed_size
        assert unsigned_size < signed_size

    def test_call_signing(self):
        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

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

    @override_switch('add-guid-to-manifest', active=True)
    def test_call_signing_add_guid(self):
        file_ = version_factory(
            addon=self.addon, file_kw={'filename': 'webextension_no_id.xpi'}
        ).file
        assert signing.sign_file(file_)

        signature_info, manifest = _get_signature_details(file_.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4
        # Need to use .startswith() since the signature from `cose.sig`
        # changes on every test-run, so we're just not going to check it
        # explicitly...
        assert manifest.startswith(
            'Manifest-Version: 1.0\n\n'
            'Name: README.md\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: MAajMoNW9rYdgU0VwiTJxfh9TF0=\n'
            'SHA256-Digest: Dj3HrJ4QDG5YPGff4YsjSqAVYKU99f3vz1ssno2Cloc=\n\n'
            'Name: manifest.json\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: 77nz8cVnruIKyRPRqnIfao1uoHw=\n'
            'SHA256-Digest: m0f3srI8vw15H8mYbQlb+adptxNt2QGXT69krfoq+T0=\n\n'
            'Name: META-INF/cose.manifest\n'
            'Digest-Algorithms: SHA1 SHA256\n'
            'SHA1-Digest: 6IHHewfjdgEaJGfD86oqWo1qel0=\n'
            'SHA256-Digest: bExoReutlIoZMatxIQ4jtgAyujR1q193Ng0tjooB2Hc=\n\n'
            'Name: META-INF/cose.sig\n'
            'Digest-Algorithms: SHA1 SHA256\n'
        )

    def _test_add_guid_existing_guid(self, file_):
        with open(file_.file.path, 'rb') as fobj:
            contents = fobj.read()
        with override_switch('add-guid-to-manifest', active=False):
            assert signing.add_guid(file_) == contents
        with override_switch('add-guid-to-manifest', active=True):
            assert signing.add_guid(file_) == contents

    def test_add_guid_existing_guid_applications(self):
        # self.file_ is "webextension.xpi", which already has a guid, as "applications"
        self._test_add_guid_existing_guid(self.file_)

    def test_add_guid_existing_guid_browser_specific_settings(self):
        file_ = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_browser_specific_settings.xpi'},
        ).file
        self._test_add_guid_existing_guid(file_)

    def test_add_guid_no_guid(self):
        file_ = version_factory(
            addon=self.addon, file_kw={'filename': 'webextension_no_id.xpi'}
        ).file
        with open(file_.file.path, 'rb') as fobj:
            contents = fobj.read()
        # with the waffle off it's the same as with an existing guid
        with override_switch('add-guid-to-manifest', active=False):
            assert signing.add_guid(file_) == contents

        # if it's on though, it's different
        with override_switch('add-guid-to-manifest', active=True):
            zip_blob = signing.add_guid(file_)
            assert zip_blob != contents
        # compare the zip contents
        with (
            zipfile.ZipFile(file_.file.path) as orig_zip,
            zipfile.ZipFile(io.BytesIO(zip_blob)) as new_zip,
        ):
            for info in orig_zip.filelist:
                if info.filename != 'manifest.json':
                    # all other files should be the same
                    orig_zip.open(info.filename).read() == new_zip.open(
                        info.filename
                    ).read()
                else:
                    # only manifest.json should have been updated
                    orig_manifest = json.load(orig_zip.open(info.filename))
                    new_manifest_blob = new_zip.open(info.filename).read()
                    new_manifest = json.loads(new_manifest_blob)
                    assert orig_manifest != new_manifest
                    assert new_manifest['browser_specific_settings']['gecko']['id'] == (
                        self.file_.addon.guid
                    )
                    assert orig_manifest == {
                        key: value
                        for key, value in new_manifest.items()
                        if key != 'browser_specific_settings'
                    }
                    # check the manifest is formatted well, with spacing and line breaks
                    assert new_manifest_blob.decode('utf8').startswith('{\n  "manifest')
            assert 'manifest.json' in (info.filename for info in orig_zip.filelist)
            assert len(orig_zip.filelist) == len(new_zip.filelist)

    def test_call_signing_too_long_guid_bug_1203365(self):
        long_guid = 'x' * 65
        hashed = hashlib.sha256(force_bytes(long_guid)).hexdigest()
        self.addon.update(guid=long_guid)
        signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

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
        long_guid = 'x' * 65
        hashed = hashlib.sha256(force_bytes(long_guid)).hexdigest()
        self.addon.update(guid=long_guid)
        assert len(self.addon.guid) > 64
        assert len(signing.get_id(self.addon)) <= 64
        assert signing.get_id(self.addon) == hashed

    def test_sign_addon_with_unicode_guid(self):
        self.addon.update(guid='NavratnePeniaze@NávratnéPeniaze')

        signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

        subject_info = signature_info.signer_certificate['subject']

        assert subject_info['common_name'] == 'NavratnePeniaze@NávratnéPeniaze'
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

    def _check_signed_correctly(self, states):
        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 5

        assert 'Name: mozilla-recommendation.json' in manifest
        assert 'Name: manifest.json' in manifest
        assert 'Name: META-INF/cose.manifest' in manifest
        assert 'Name: META-INF/cose.sig' in manifest

        recommendation_data = _get_recommendation_data(self.file_.file.path)
        assert recommendation_data['addon_id'] == 'xxxxx'
        assert sorted(recommendation_data['states']) == states

    def test_call_signing_promoted(self):
        # This is the usual process for promoted add-ons, they're
        # in "pending" and only *after* we approve and sign them they will
        # become "promoted" for that group. If their promoted group changes
        # we won't sign further versions as promoted.
        self.make_addon_promoted(self.file_.version.addon, LINE)

        # it's promoted for all applications, but it's the same state for both
        # desktop and android so don't include twice.
        self._check_signed_correctly(states=['line'])

    def test_call_signing_promoted_recommended(self):
        self.make_addon_promoted(self.file_.version.addon, RECOMMENDED)

        # Recommended has different states for desktop and android
        self._check_signed_correctly(states=['recommended', 'recommended-android'])

    def test_call_signing_promoted_recommended_android_only(self):
        self.make_addon_promoted(self.file_.version.addon, RECOMMENDED)
        self.file_.version.addon.promotedaddon.update(application_id=amo.ANDROID.id)

        # Recommended has different states for desktop and android
        self._check_signed_correctly(states=['recommended-android'])

    def test_call_signing_promoted_unlisted(self):
        # Unlisted versions, even when the add-on is in promoted group, should
        # never be signed as promoted.
        self.make_addon_promoted(self.file_.version.addon, RECOMMENDED)
        self.version.update(channel=amo.CHANNEL_UNLISTED)

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4

        assert 'Name: mozilla-recommendation.json' not in manifest

    def test_call_signing_promoted_no_special_autograph_group(self):
        # SPOTLIGHT addons aren't signed differently.
        self.make_addon_promoted(self.file_.version.addon, SPOTLIGHT)

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4

        assert 'Name: mozilla-recommendation.json' not in manifest


@override_settings(ENABLE_ADDON_SIGNING=True)
class TestTransactionRelatedSigning(TransactionTestCase):
    def setUp(self):
        super().setUp()

        self.addon = amo.tests.addon_factory(
            file_kw={
                'filename': 'webextension.xpi',
            }
        )
        self.version = self.addon.current_version

        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

    @mock.patch('olympia.git.utils.create_git_extraction_entry')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_creates_git_extraction_entry_after_signing(self, create_entry_mock):
        with transaction.atomic():
            signing.sign_file(self.version.file)

        create_entry_mock.assert_called_once_with(version=self.version)

    @mock.patch('olympia.git.utils.create_git_extraction_entry')
    @override_switch('enable-uploads-commit-to-git-storage', active=True)
    def test_does_not_create_git_extraction_entry_on_error(self, create_entry_mock):
        def call_sign_file():
            signing.sign_file(self.version.file)
            # raise ValueError after the sign_file call so that
            # the extraction is queued via the on_commit hook
            # but the atomic block won't complete.
            raise ValueError()

        with pytest.raises(ValueError):
            with transaction.atomic():
                call_sign_file()

        assert not create_entry_mock.called


class TestTasks(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.addon = amo.tests.addon_factory(
            name='Rændom add-on',
            version_kw={'version': '0.0.1'},
            file_kw={'filename': 'webextension.xpi'},
        )
        self.version = self.addon.current_version
        self.max_appversion = self.version.apps.first().max
        self.set_max_appversion('48')
        self.file_ = self.version.file

    def tearDown(self):
        if os.path.exists(self.get_backup_file_path()):
            os.unlink(self.get_backup_file_path())
        super().tearDown()

    def get_backup_file_path(self):
        return f'{self.file_.file.path}.backup_signature'

    def set_max_appversion(self, version):
        """Set self.max_appversion to the given version."""
        self.max_appversion.update(version=version, version_int=version_int(version))

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
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1'
            self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_bump_version_in_model(self, mock_sign_file):
        file_hash = self.file_.generate_hash()
        assert self.version.version == '0.0.1'
        tasks.sign_addons([self.addon.pk])
        # We mocked sign_file(), but the file on disk should have been
        # rewritten by update_version_number() in sign_addons().
        assert mock_sign_file.call_count == 1
        self.version.reload()
        assert self.version.version == '0.0.1.1-signed'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash != self.file_.generate_hash()
        self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_full(self, mock_sign_file):
        """Use the signing server if files are approved."""
        self.file_.update(status=amo.STATUS_APPROVED)
        tasks.sign_addons([self.addon.pk])
        mock_sign_file.assert_called_with(self.file_)

    def assert_not_signed(self, mock_sign_file, file_hash):
        assert not mock_sign_file.called
        self.version.reload()
        assert self.version.version == '0.0.1'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash == self.file_.generate_hash()
        self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_filename(self, mock_sign_file):
        """Sign files which have non-ascii filenames."""
        old_file_path = self.file_.file.path
        old_file_dirs = os.path.dirname(self.file_.file.name)
        self.file_.file.name = os.path.join(old_file_dirs, 'wébextension.zip')
        self.file_.save()
        os.rename(old_file_path, self.file_.file.path)
        file_hash = self.file_.generate_hash()
        assert self.version.version == '0.0.1'
        tasks.sign_addons([self.addon.pk])
        assert mock_sign_file.called
        self.version.reload()
        assert self.version.version == '0.0.1.1-signed'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash != self.file_.generate_hash()
        self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_non_ascii_version(self, mock_sign_file):
        """Sign versions which have non-ascii version numbers."""
        self.version.update(version='é0.0.1')
        file_hash = self.file_.generate_hash()
        assert self.version.version == 'é0.0.1'
        tasks.sign_addons([self.addon.pk])
        assert mock_sign_file.called
        self.version.reload()
        assert self.version.version == 'é0.0.1.1-signed'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash != self.file_.generate_hash()
        self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_bump_old_versions_default_compat(self, mock_sign_file):
        """Sign files which are old, but default to compatible."""
        file_hash = self.file_.generate_hash()
        assert self.version.version == '0.0.1'
        self.set_max_appversion('4')
        tasks.sign_addons([self.addon.pk])
        assert mock_sign_file.called
        self.version.reload()
        assert self.version.version == '0.0.1.1-signed'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash != self.file_.generate_hash()
        self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_resign_and_bump_version_in_model(self, mock_sign_file):
        fname = './src/olympia/files/fixtures/files/webextension_signed_already.xpi'
        with amo.tests.copy_file(fname, self.file_.file.path, overwrite=True):
            self.file_.update(is_signed=True)
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1.1-signed'
            self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
            assert file_hash != self.file_.generate_hash()
            self.assert_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_version_bad_zipfile(self, mock_sign_file):
        with amo.tests.copy_file(__file__, self.file_.file.path, overwrite=True):
            file_hash = self.file_.generate_hash()
            assert self.version.version == '0.0.1'
            tasks.sign_addons([self.addon.pk])
            assert not mock_sign_file.called
            self.version.reload()
            assert self.version.version == '0.0.1'
            self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
            assert file_hash == self.file_.generate_hash()
            self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_sign_dont_bump_sign_error(self, mock_sign_file):
        mock_sign_file.side_effect = IOError()
        file_hash = self.file_.generate_hash()
        assert self.version.version == '0.0.1'
        tasks.sign_addons([self.addon.pk])
        assert mock_sign_file.called
        self.version.reload()
        assert self.version.version == '0.0.1'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash == self.file_.generate_hash()
        self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_dont_bump_not_signed(self, mock_sign_file):
        mock_sign_file.return_value = None  # Pretend we didn't sign.
        file_hash = self.file_.generate_hash()
        assert self.version.version == '0.0.1'
        tasks.sign_addons([self.addon.pk])
        assert mock_sign_file.called
        self.version.reload()
        assert self.version.version == '0.0.1'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash == self.file_.generate_hash()
        self.assert_no_backup()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_resign_only_current_versions(self, mock_sign_file):
        new_current_version = amo.tests.version_factory(
            addon=self.addon, version='0.0.2', file_kw={'filename': 'webextension.xpi'}
        )
        new_file = new_current_version.file
        file_hash = self.file_.generate_hash()
        new_file_hash = new_file.generate_hash()

        tasks.sign_addons([self.addon.pk])

        # Only one signing call since we only sign the most recent
        # versions
        assert mock_sign_file.call_count == 1

        new_current_version.reload()
        assert new_current_version.version == '0.0.2.1-signed'
        new_file.reload()  # Otherwise new_file.file doesn't get re-opened
        assert new_file_hash != new_file.generate_hash()

        # Verify that the old version hasn't been resigned
        self.version.reload()
        assert self.version.version == '0.0.1'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert file_hash == self.file_.generate_hash()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_mail_cose_subject(self, mock_sign_file):
        self.file_.update(status=amo.STATUS_APPROVED)
        AddonUser.objects.create(addon=self.addon, user_id=999)
        tasks.sign_addons([self.addon.pk])
        mock_sign_file.assert_called_with(self.file_)

        assert 'stronger signature' in mail.outbox[0].message().as_string()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_sign_mail_cose_message_contains_addon_name(self, mock_sign_file):
        self.file_.update(status=amo.STATUS_APPROVED)
        AddonUser.objects.create(addon=self.addon, user_id=999)
        tasks.sign_addons([self.addon.pk])
        mock_sign_file.assert_called_with(self.file_)

        assert 'Rændom add-on' in mail.outbox[0].message().as_string()


@pytest.mark.parametrize(
    ('old', 'new'),
    [
        ('1.1', '1.1.1-signed'),
        ('1.1.1-signed.1', '1.1.1-signed.1.1-signed'),
        ('1.1.1-signed', '1.1.1-signed-2'),
        ('1.1.1-signed-3', '1.1.1-signed-4'),
        ('1.1.1-signed.1-signed-16', '1.1.1-signed.1-signed-17'),
    ],
)
def test_get_new_version_number(old, new):
    assert tasks.get_new_version_number(old) == new


class TestSignatureInfo:
    @pytest.fixture(autouse=True)
    def setup(self):
        fixture_path = (
            'src/olympia/lib/crypto/tests/mozilla-generated-by-openssl.pkcs7.der'
        )

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
        assert self.info.issuer == collections.OrderedDict(
            [
                ('country_name', 'US'),
                ('state_or_province_name', 'CA'),
                ('locality_name', 'Mountain View'),
                ('organization_name', 'Addons Test Signing'),
                ('common_name', 'test.addons.signing.root.ca'),
                ('email_address', 'opsec+stagerootaddons@mozilla.com'),
            ]
        )

    def test_signer_certificate(self):
        assert (
            self.info.signer_certificate['serial_number']
            == self.info.signer_serial_number
        )
        assert self.info.signer_certificate['issuer'] == self.info.issuer

        expected_subject_public_key_info = collections.OrderedDict(
            [
                (
                    'algorithm',
                    collections.OrderedDict(
                        [('algorithm', 'rsa'), ('parameters', None)]
                    ),
                ),
                (
                    'public_key',
                    collections.OrderedDict(
                        [
                            (
                                'modulus',
                                int(
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
                                    '841847040037917474056678747905247'
                                ),
                            ),
                            ('public_exponent', 65537),
                        ]
                    ),
                ),
            ]
        )
        expected = collections.OrderedDict(
            [
                ('version', 'v3'),
                ('serial_number', 1498181554500),
                (
                    'signature',
                    collections.OrderedDict(
                        [('algorithm', 'sha256_rsa'), ('parameters', None)]
                    ),
                ),
                (
                    'issuer',
                    collections.OrderedDict(
                        [
                            ('country_name', 'US'),
                            ('state_or_province_name', 'CA'),
                            ('locality_name', 'Mountain View'),
                            ('organization_name', 'Addons Test Signing'),
                            ('common_name', 'test.addons.signing.root.ca'),
                            ('email_address', 'opsec+stagerootaddons@mozilla.com'),
                        ]
                    ),
                ),
                (
                    'validity',
                    collections.OrderedDict(
                        [
                            (
                                'not_before',
                                datetime.datetime(
                                    2017, 6, 23, 1, 32, 34, tzinfo=pytz.utc
                                ),
                            ),
                            (
                                'not_after',
                                datetime.datetime(
                                    2027, 6, 21, 1, 32, 34, tzinfo=pytz.utc
                                ),
                            ),
                        ]
                    ),
                ),
                (
                    'subject',
                    collections.OrderedDict(
                        [
                            ('organizational_unit_name', 'Testing'),
                            ('country_name', 'US'),
                            ('locality_name', 'Mountain View'),
                            ('organization_name', 'Addons Testing'),
                            ('state_or_province_name', 'CA'),
                            ('common_name', '{02b860db-e71f-48d2-a5a0-82072a93d33c}'),
                        ]
                    ),
                ),
                (
                    'subject_public_key_info',
                    expected_subject_public_key_info,
                ),
                ('issuer_unique_id', None),
                ('subject_unique_id', None),
                ('extensions', None),
            ]
        )

        assert self.info.signer_certificate == expected
