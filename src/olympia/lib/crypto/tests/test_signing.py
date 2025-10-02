import collections
import datetime
import hashlib
import io
import json
import os
import zipfile
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.test.testcases import TransactionTestCase
from django.test.utils import override_settings
from django.utils.encoding import force_bytes, force_str

import pytest
import pytz
import responses

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_default_webext_appversion,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_addon_file
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.lib.crypto import signing, tasks
from olympia.versions.compare import VersionString, version_int


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
                    assert (
                        orig_zip.open(info.filename).read()
                        == new_zip.open(info.filename).read()
                    )
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
        self.make_addon_promoted(self.file_.version.addon, PROMOTED_GROUP_CHOICES.LINE)

        # it's promoted for all applications, but it's the same state for both
        # desktop and android so don't include twice.
        self._check_signed_correctly(states=['line'])

    def test_call_signing_promoted_recommended(self):
        self.make_addon_promoted(
            self.file_.version.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED
        )

        # Recommended has different states for desktop and android
        self._check_signed_correctly(states=['recommended', 'recommended-android'])

    def test_call_signing_promoted_recommended_android_only(self):
        self.make_addon_promoted(
            self.file_.version.addon,
            PROMOTED_GROUP_CHOICES.RECOMMENDED,
            apps=[amo.ANDROID],
        )

        # Recommended has different states for desktop and android
        self._check_signed_correctly(states=['recommended-android'])

    def test_call_signing_promoted_unlisted(self):
        # Unlisted versions, even when the add-on is in promoted group, should
        # never be signed as promoted.
        self.make_addon_promoted(
            self.file_.version.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.version.update(channel=amo.CHANNEL_UNLISTED)

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4

        assert 'Name: mozilla-recommendation.json' not in manifest

    def test_call_signing_promoted_no_special_autograph_group(self):
        # SPOTLIGHT addons aren't signed differently.
        self.make_addon_promoted(
            self.file_.version.addon, PROMOTED_GROUP_CHOICES.SPOTLIGHT
        )

        assert signing.sign_file(self.file_)

        signature_info, manifest = _get_signature_details(self.file_.file.path)

        subject_info = signature_info.signer_certificate['subject']
        assert subject_info['common_name'] == 'xxxxx'
        assert manifest.count('Name: ') == 4

        assert 'Name: mozilla-recommendation.json' not in manifest


@mock.patch('olympia.lib.crypto.tasks.sign_file')
class TestTasks(TestCase):
    fixtures = ['base/users']

    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()

    def setUp(self):
        super().setUp()
        self.addon = amo.tests.addon_factory(
            name='Rændom add-on',
            guid='@webextension-guid',
            version_kw={
                'version': '0.0.1',
                'created': datetime.datetime(2019, 4, 1),
                'min_app_version': '48.0',
                'max_app_version': '*',
                'approval_notes': 'Hey reviewers, this is for you',
            },
            file_kw={'filename': 'webextension.xpi'},
            users=[user_factory(last_login_ip='10.0.1.2')],
        )
        self.version = self.addon.current_version
        self.file_ = self.version.file
        self.original_file_hash = self.file_.generate_hash()

    def assert_existing_version_was_untouched(self):
        self.version.reload()
        assert self.version.version == '0.0.1'
        self.file_.reload()  # Otherwise self.file_.file doesn't get re-opened
        assert self.original_file_hash == self.file_.generate_hash()

    def test_no_bump_unreviewed(self, mock_sign_file):
        """Don't bump nor sign unreviewed files."""
        for status in amo.UNREVIEWED_FILE_STATUSES:
            self.file_.update(status=status)
            assert self.version.version == '0.0.1'
            tasks.bump_and_resign_addons([self.addon.pk])

            self.addon.reload()
            assert self.addon.versions.count() == 1
            assert self.addon.current_version == self.version
            assert not mock_sign_file.called
            self.assert_existing_version_was_untouched()
            assert len(mail.outbox) == 0

    def test_sign_bump(self, mock_sign_file):
        tasks.bump_and_resign_addons([self.addon.pk])

        self.addon.reload()
        assert self.addon.versions.count() == 2
        assert self.addon.current_version != self.version
        new_version = self.addon.current_version
        new_file = new_version.file
        assert new_version.version == '0.0.2resigned1'
        # We mocked sign_file(), but the new file on disk should have been
        # written by copy_xpi_with_new_version_number() in sign_addons().
        assert new_file.file.path
        assert os.path.exists(new_file.file.path)
        with zipfile.ZipFile(new_file.file.path) as zipf:
            assert (
                json.loads(zipf.read('manifest.json'))['version'] == new_version.version
            )

        assert mock_sign_file.call_count == 1
        assert mock_sign_file.call_args[0] == (new_file,)

        assert self.version.compatible_apps  # Still there, untouched.
        assert amo.FIREFOX in new_version.compatible_apps
        assert (
            new_version.compatible_apps[amo.FIREFOX].min
            == self.version.compatible_apps[amo.FIREFOX].min
        )
        assert (
            new_version.compatible_apps[amo.FIREFOX].max
            == self.version.compatible_apps[amo.FIREFOX].max
        )
        # Shouldn't be the same instance.
        assert self.version.compatible_apps != new_version.compatible_apps

        assert self.version.approval_notes
        assert self.version.approval_notes == new_version.approval_notes

        assert len(mail.outbox) == 1
        assert 'stronger signature' in mail.outbox[0].message().as_string()
        assert 'Rændom add-on' in mail.outbox[0].message().as_string()
        assert mail.outbox[0].to == [self.addon.authors.all()[0].email]
        assert mail.outbox[0].reply_to == ['mozilla-add-ons-community@mozilla.com']

        activity = ActivityLog.objects.latest('pk')
        assert activity.action == amo.LOG.VERSION_RESIGNED.id
        assert activity.arguments == [self.addon, new_version, self.version.version]

        assert new_version.license == self.version.license

        # Make sure we haven't touched the existing version and its file.
        self.assert_existing_version_was_untouched()

    def test_sign_bump_non_ascii_filename(self, mock_sign_file):
        """Sign files which have non-ascii filenames."""
        old_file_path = self.file_.file.path
        old_file_dirs = os.path.dirname(self.file_.file.name)
        self.file_.file.name = os.path.join(old_file_dirs, 'wébextension.zip')
        self.original_file_hash = self.file_.hash = self.file_.generate_hash()
        self.file_.save()
        os.rename(old_file_path, self.file_.file.path)

        self.test_sign_bump()

    def test_no_bump_bad_zipfile(self, mock_sign_file):
        # Overwrite the xpi with this file - a python file, it should ignore it.
        with amo.tests.copy_file(__file__, self.file_.file.path, overwrite=True):
            self.original_file_hash = self.file_.generate_hash()

            tasks.bump_and_resign_addons([self.addon.pk])

            self.addon.reload()
            assert self.addon.versions.count() == 1
            assert self.addon.current_version == self.version
            assert not mock_sign_file.called
            self.assert_existing_version_was_untouched()
            assert len(mail.outbox) == 0

    def test_dont_sign_dont_bump_sign_error(self, mock_sign_file):
        mock_sign_file.side_effect = IOError()

        # IOError should be caught, this shouldn't raise.
        tasks.bump_and_resign_addons([self.addon.pk])

        self.addon.reload()

        # Signing was called.
        assert mock_sign_file.call_count == 1

        # Signing error should have caused the transaction that created the
        # Version to be rolled back (technically since we're in a regular
        # TestCase that was done with a savepoint).
        assert self.addon.versions.count() == 1
        assert self.addon.current_version == self.version

        # Existing version untouched no matter what.
        self.assert_existing_version_was_untouched()

        # No email since we didn't succeed.
        assert len(mail.outbox) == 0

    def test_resign_only_current_versions(self, mock_sign_file):
        amo.tests.version_factory(
            addon=self.addon, version='0.0.2', file_kw={'filename': 'webextension.xpi'}
        )
        assert self.addon.reload().current_version.version == '0.0.2'

        tasks.bump_and_resign_addons([self.addon.pk])

        # Only one signing call since we only sign the most recent
        # versions
        assert mock_sign_file.call_count == 1

        new_current_version = self.addon.reload().current_version
        assert new_current_version.version == '0.0.3resigned1'

    @mock.patch('olympia.addons.models.Addon.resolve_webext_translations')
    def test_resign_bypass_name_checks(self, mock_resolve_message, mock_sign_file):
        # Would violate trademark rule, as it contains "Firefox" but doesn't
        # end with "for Firefox", and the author doesn't have special
        # permissions.
        mock_resolve_message.return_value = {'name': 'My Firefox Add-on'}

        self.test_sign_bump()

    def test_resign_carry_over_promotion(self, mock_sign_file):
        self.make_addon_promoted(
            self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )
        assert self.addon.publicly_promoted_groups
        # Should have an approval for Firefox and one for Android.
        assert self.addon.current_version.promoted_versions.count() == 2

        tasks.bump_and_resign_addons([self.addon.pk])

        del self.addon.publicly_promoted_groups  # Reload the cached property.
        assert self.addon.publicly_promoted_groups
        # Should have an approval for Firefox and one for Android.
        assert self.addon.current_version.promoted_versions.count() == 2

    def test_resign_doesnt_carry_over_unapproved_promotion(self, mock_sign_file):
        self.make_addon_promoted(
            self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=False
        )
        assert not self.addon.publicly_promoted_groups
        assert self.addon.current_version.promoted_versions.count() == 0

        tasks.bump_and_resign_addons([self.addon.pk])

        del self.addon.publicly_promoted_groups  # Reload the cached property.
        assert not self.addon.publicly_promoted_groups
        assert self.addon.current_version.promoted_versions.count() == 0

    def test_resign_multiple_emails_same_addon(self, mock_sign_file):
        self.addon.authors.add(user_factory(last_login_ip='127.0.0.2'))
        self.addon.authors.add(
            user_factory(last_login_ip='127.0.0.3'),
            through_defaults={'role': amo.AUTHOR_ROLE_DEV},
        )

        tasks.bump_and_resign_addons([self.addon.pk])

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [self.addon.authors.all().order_by('pk')[0].email]
        assert mail.outbox[1].to == [self.addon.authors.all().order_by('pk')[1].email]

    def test_bump_original_manifest_contains_comments(self, mock_sign_file):
        manifest_with_comments = """
        {
            // Requiréd
            "manifest_version": 2,
            "name": "My Extension",
            "description": "haupt\\u005fstra\\u00dfe", // Recommended
            "version": "0.0.1",
            // Nice.
            "applications": {
                "gecko": {
                    "id": "@webextension-guid"
                }
            }
        }
        """
        with zipfile.ZipFile(self.file_.file.path, 'w') as z:
            z.writestr('manifest.json', manifest_with_comments)

        self.original_file_hash = self.file_.hash = self.file_.generate_hash()
        self.file_.save()

        self.test_sign_bump()


class TestBumpTaskWithTransactions(TransactionTestCase):
    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)
        create_default_webext_appversion()

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_theme_preview(self, mock_sign_file):
        addon = addon_factory(
            file_kw={'filename': get_addon_file('static_theme.zip')},
            version_kw={'version': '2.9'},
            users=[user_factory(last_login_ip='10.0.1.4')],
            type=amo.ADDON_STATICTHEME,
        )
        tasks.bump_and_resign_addons([addon.pk])

        assert mock_sign_file.call_count == 1
        new_current_version = addon.reload().current_version
        assert new_current_version.version == '2.10resigned1'

        assert new_current_version.previews.count() == 2


@pytest.mark.parametrize(
    ('old_version', 'expected_version'),
    [
        ('1.1', '1.2resigned1'),
        ('1.2.3resigned1', '1.2.4resigned1'),
        ('1.1.1b', '1.1.2resigned1'),
        ('1.1.1b3', '1.1.2resigned1'),
        ('1.1.1b.1c-16', '1.1.1b.2resigned1'),
        ('1.2.3.4', '1.2.3.5resigned1'),
        ('2.0a1', '2.1resigned1'),
        ('0.2.0b1', '0.2.1resigned1'),
        ('40007.2024.3.42c', '40007.2024.3.43resigned1'),
        ('1.01b.78', '1.1b.79resigned1'),
        ('1.2.5_5', '1.2.6resigned1'),
        ('714.16G', '714.17resigned1'),
        ('999999999999999999999999999999', '1000000000000000000000000000000resigned1'),
    ],
)
def test_get_new_version_number(old_version, expected_version):
    new_version = tasks.get_new_version_number(old_version)
    assert new_version == VersionString(expected_version)
    assert str(new_version) == expected_version


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
