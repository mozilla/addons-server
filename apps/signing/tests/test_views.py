import os
from datetime import datetime, timedelta

from django.core import mail
from django.core.urlresolvers import reverse

import mock
from rest_framework.response import Response

import amo
from addons.models import Addon, AddonUser
from api.tests.utils import APIAuthTestCase
from files.models import File, FileUpload
from signing.views import VersionView
from users.models import UserProfile
from versions.models import Version


class MockSideEffectException(Exception):
    """Raised by mocks."""


class SigningAPITestCase(APIAuthTestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.api_key = self.create_api_key(self.user, str(self.user.pk) + ':f')


class BaseUploadVersionCase(SigningAPITestCase):

    def setUp(self):
        super(BaseUploadVersionCase, self).setUp()
        self.guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        self.view = VersionView.as_view()

    def url(self, guid, version, pk=None):
        args = [guid, version]
        if pk is not None:
            args.append(pk)
        return reverse('signing.version', args=args)

    def create_version(self, version):
        response = self.put(self.url(self.guid, version), version)
        assert response.status_code in [201, 202]

    def xpi_filepath(self, addon, version):
        return os.path.join(
            'apps', 'signing', 'fixtures',
            '{addon}-{version}.xpi'.format(addon=addon, version=version))

    def put(self, url=None, version='3.0', addon='@upload-version',
            filename=None):
        if filename is None:
            filename = self.xpi_filepath(addon, version)
        if url is None:
            url = self.url(addon, version)
        with open(filename) as upload:
            return self.client.put(url, {'upload': upload},
                                   HTTP_AUTHORIZATION=self.authorization())


class TestUploadVersion(BaseUploadVersionCase):

    def test_not_authenticated(self):
        # Use self.client.put so that we don't add the authorization header.
        response = self.client.put(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    @mock.patch('devhub.views.auto_sign_version')
    def test_addon_does_not_exist(self, sign_version):
        guid = '@create-version'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.put(addon=guid, version='1.0')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert not addon.is_listed
        assert addon.status == amo.STATUS_LITE
        sign_version.assert_called_with(addon.latest_version)

    def test_user_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_version_does_not_match_install_rdf(self):
        response = self.put(self.url(self.guid, '2.5'))
        assert response.status_code == 400
        assert response.data['error'] == 'Version does not match install.rdf.'

    def test_version_already_exists(self):
        response = self.put(self.url(self.guid, '2.1.072'), version='2.1.072')
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

    @mock.patch('devhub.views.Version.from_upload')
    def test_no_version_yet(self, from_upload):
        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    @mock.patch('devhub.views.auto_sign_version')
    def test_version_added(self, sign_version):
        assert Addon.objects.get(guid=self.guid).status == amo.STATUS_PUBLIC
        qs = Version.objects.filter(addon__guid=self.guid, version='3.0')
        assert not qs.exists()

        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == '3.0'
        assert version.statuses[0][1] == amo.STATUS_PUBLIC
        assert version.addon.status == amo.STATUS_PUBLIC
        sign_version.assert_called_with(version)

    def test_version_already_uploaded(self):
        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

    def test_version_failed_review(self):
        self.create_version('3.0')
        version = Version.objects.get(addon__guid=self.guid, version='3.0')
        version.update(reviewed=datetime.today())
        version.files.get().update(reviewed=datetime.today(),
                                   status=amo.STATUS_DISABLED)

        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        # Verify that you can check the status after upload (#953).
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    @mock.patch('devhub.views.auto_sign_version')
    def test_version_added_is_experiment(self, sign_version):
        self.grant_permission(self.user, 'Experiments:submit')
        guid = 'experiment@xpi'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.put(
            addon=guid, version='0.1',
            filename='apps/files/fixtures/files/experiment.xpi')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert not addon.is_listed
        assert addon.status == amo.STATUS_LITE
        sign_version.assert_called_with(addon.latest_version)

    @mock.patch('devhub.views.auto_sign_version')
    def test_version_added_is_experiment_reject_no_perm(self, sign_version):
        guid = 'experiment@xpi'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.put(
            addon=guid, version='0.1',
            filename='apps/files/fixtures/files/experiment.xpi')
        assert response.status_code == 400
        assert response.data['error'] == (
            'You cannot submit this type of add-on')


class TestCheckVersion(BaseUploadVersionCase):

    def test_not_authenticated(self):
        # Use self.client.get so that we don't add the authorization header.
        response = self.client.get(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    def test_addon_does_not_exist(self):
        response = self.get(self.url('foo', '12.5'))
        assert response.status_code == 404
        assert response.data['error'] == 'Could not find add-on with id "foo".'

    def test_user_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_version_does_not_exist(self):
        response = self.get(self.url(self.guid, '2.5'))
        assert response.status_code == 404
        assert (response.data['error'] ==
                'No uploaded file for that addon and version.')

    def test_version_exists(self):
        self.create_version('3.0')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_exists_with_pk(self):
        # Mock Version.from_upload so the Version won't be created.
        with mock.patch('devhub.tasks.Version.from_upload'):
            self.create_version('3.0')
        upload = FileUpload.objects.latest()
        upload.update(created=datetime.today() - timedelta(hours=1))

        self.create_version('3.0')
        newer_upload = FileUpload.objects.latest()
        assert newer_upload != upload

        response = self.get(self.url(self.guid, '3.0', upload.pk))
        assert response.status_code == 200
        assert response.data['pk'] == upload.pk
        assert 'processed' in response.data

    @mock.patch('devhub.tasks.submit_file')
    def test_version_exists_with_pk_not_owner(self, submit_file):
        orig_user, orig_api_key = self.user, self.api_key

        # This will create a version for the add-on with guid @create-version
        # using a new user.
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.put(addon='@create-version', version='1.0')
        assert response.status_code == 201
        upload = FileUpload.objects.latest()

        # Check that the user that created the upload can access it properly.
        response = self.get(self.url('@create-version', '1.0', upload.pk))
        assert response.status_code == 200
        assert 'processed' in response.data

        # This will create a version for the add-on from the fixture with the
        # regular fixture user.
        self.user, self.api_key = orig_user, orig_api_key
        self.create_version('3.0')

        # Check that we can't access the FileUpload by pk even if we pass in
        # an add-on and version that we own if we don't own the FileUpload.
        response = self.get(self.url(self.guid, '3.0', upload.pk))
        assert response.status_code == 404
        assert 'error' in response.data

    def test_version_download_url(self):
        version_string = '3.0'
        qs = File.objects.filter(version__addon__guid=self.guid,
                                 version__version=version_string)
        assert not qs.exists()
        self.create_version(version_string)
        response = self.get(self.url(self.guid, version_string))
        assert response.status_code == 200
        file_ = qs.get()
        assert response.data['files'][0]['download_url'] == \
            file_.get_signed_url('api')

    def test_file_hash(self):
        version_string = '3.0'
        qs = File.objects.filter(version__addon__guid=self.guid,
                                 version__version=version_string)
        assert not qs.exists()
        self.create_version(version_string)
        response = self.get(self.url(self.guid, version_string))
        assert response.status_code == 200
        file_ = qs.get()

        filename = self.xpi_filepath('@upload-version', version_string)
        assert response.data['files'][0]['hash'] == \
            file_.generate_hash(filename=filename)

    def test_has_failed_upload(self):
        addon = Addon.objects.get(guid=self.guid)
        FileUpload.objects.create(addon=addon, version='3.0')
        self.create_version('3.0')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data


class TestSignedFile(BaseUploadVersionCase):

    def setUp(self):
        super(TestSignedFile, self).setUp()
        self.file_ = self.create_file()
        self.filename = self.xpi_filepath(addon='@upload-version',
                                          version='3.0')
        self.now = datetime.now()
        self.now_str = self.now.strftime('%Y%m%d%H%M%S')

    def url(self):
        return reverse('signing.file', args=[self.file_.pk])

    def create_file(self):
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(is_listed=False)
        AddonUser.objects.create(user=self.user, addon=self.addon)
        self.version = Version.objects.create(addon=self.addon)
        return File.objects.create(version=self.version,
                                   filename='extension.xpi')

    def post(self, data=None):
        data = data or {}
        with open(self.filename) as upload:
            data.update({'upload': upload})
            return self.client.post(self.url(), data,
                                    HTTP_AUTHORIZATION=self.authorization())

    def allow_user_repack_api(self):
        """Give self.user permission to use the repack API."""
        self.grant_permission(self.user, 'Addons:Edit')

    def test_can_download_once_authenticated(self):
        response = self.get(self.url())
        assert response.status_code == 302
        assert response['X-Target-Digest'] == self.file_.hash

    def test_cannot_download_without_authentication(self):
        response = self.client.get(self.url())  # no auth
        assert response.status_code == 401

    def test_api_relies_on_version_downloader(self):
        with mock.patch('versions.views.download_file') as df:
            df.return_value = Response({})
            self.get(self.url())
        assert df.called is True
        assert df.call_args[0][0].user == self.user
        assert df.call_args[0][1] == str(self.file_.pk)

    def test_post_needs_admin(self):
        response = self.post()
        assert response.status_code == 403

        self.allow_user_repack_api()
        response = self.post()
        assert response.status_code == 400  # No "repack_reason" provided.

    @mock.patch('signing.views.shutil.copy')
    def test_post_needs_repack_reason(self, shutil_copy_mock):
        shutil_copy_mock.side_effect = MockSideEffectException
        self.allow_user_repack_api()
        response = self.post()
        assert response.status_code == 400  # No "repack_reason" provided.

        with self.assertRaises(MockSideEffectException):
            response = self.post(data={'repack_reason': 'foobar'})

    @mock.patch('signing.views.shutil.copy')
    def test_post_checks_addon_id(self, shutil_copy_mock):
        shutil_copy_mock.side_effect = MockSideEffectException
        self.allow_user_repack_api()
        with self.assertRaises(MockSideEffectException):
            response = self.post(data={'repack_reason': 'foobar'})

        self.addon.update(guid='@foo-bar')
        response = self.post(data={'repack_reason': 'foobar'})
        assert response.status_code == 403  # Add-on id doesn't match.

    @mock.patch('signing.views.datetime')
    @mock.patch('signing.views.shutil.copy')
    def test_post_backups_file(self, shutil_copy_mock, datetime_mock):
        shutil_copy_mock.side_effect = MockSideEffectException
        datetime_mock.now.return_value = self.now
        self.allow_user_repack_api()
        with self.assertRaises(MockSideEffectException):
            self.post(data={'repack_reason': 'foobar'})
        shutil_copy_mock.assert_called_once_with(
            self.file_.file_path,
            '{}.repack-{}'.format(self.file_.file_path, self.now_str))

    @mock.patch('signing.views.datetime')
    @mock.patch('signing.views.update_version_number')
    @mock.patch('signing.views.shutil.copy')
    def test_post_updates_version_number(self, shutil_copy_mock,
                                         update_version_number_mock,
                                         datetime_mock):
        datetime_mock.now.return_value = self.now
        self.allow_user_repack_api()
        self.post(data={'repack_reason': 'foobar'})
        update_version_number_mock.assert_called_once_with(
            self.file_, '3.0.1-repack-{}'.format(self.now_str))

    @mock.patch('signing.views.sign_file')
    @mock.patch('signing.views.shutil.copy')
    def test_post_sign_file_if_signed(self, shutil_copy_mock, sign_file_mock):
        self.allow_user_repack_api()
        self.post(data={'repack_reason': 'foobar'})
        assert not sign_file_mock.called

        self.file_.update(is_signed=True)
        self.post(data={'repack_reason': 'foobar'})
        sign_file_mock.assert_called_once_with(self.file_, mock.ANY)

    @mock.patch('signing.views.datetime')
    @mock.patch('signing.views.shutil.copy')
    def test_post_bump_version_version(self, shutil_copy_mock, datetime_mock):
        datetime_mock.now.return_value = self.now
        self.allow_user_repack_api()
        assert self.version.version == '0.1'
        self.post(data={'repack_reason': 'foobar'})
        assert self.version.reload().version == '3.0.1-repack-{}'.format(
            self.now_str)

    @mock.patch('signing.views.shutil.copy')
    def test_post_sends_email(self, shutil_copy_mock):
        self.allow_user_repack_api()
        self.post(data={'repack_reason': 'foobar'})
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.subject == (
            'Mozilla Add-ons: Delicious Bookmarks has been repacked on AMO')
        assert 'foobar' in email.body
        assert email.to == [self.user.email, self.user.email]
