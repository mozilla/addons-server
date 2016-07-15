# -*- coding: utf-8 -*
import os
import json
from datetime import datetime, timedelta

from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils import translation

import mock
from rest_framework.response import Response

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser
from olympia.api.tests.utils import APIKeyAuthTestCase
from olympia.applications.models import AppVersion
from olympia.devhub import tasks
from olympia.files.models import File, FileUpload
from olympia.signing.views import VersionView
from olympia.users.models import UserProfile
from olympia.versions.models import Version


class SigningAPITestCase(APIKeyAuthTestCase):
    fixtures = ['base/addon_3615', 'base/user_4043307']

    def setUp(self):
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.api_key = self.create_api_key(self.user, str(self.user.pk) + ':f')


class BaseUploadVersionCase(SigningAPITestCase):

    def setUp(self):
        super(BaseUploadVersionCase, self).setUp()
        self.guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        self.view = VersionView.as_view()
        create_version_patcher = mock.patch(
            'olympia.devhub.tasks.create_version_for_upload',
            tasks.create_version_for_upload.non_atomic)
        self.create_version_for_upload = create_version_patcher.start()
        self.addCleanup(create_version_patcher.stop)

        auto_sign_version_patcher = mock.patch(
            'olympia.devhub.views.auto_sign_version')
        self.auto_sign_version = auto_sign_version_patcher.start()
        self.addCleanup(auto_sign_version_patcher.stop)

    def url(self, guid, version, pk=None):
        if guid is None:
            args = [version]
        else:
            args = [guid, version]
        if pk is not None:
            args.append(pk)
        return reverse('signing.version', args=args)

    def create_version(self, version):
        response = self.request('PUT', self.url(self.guid, version), version)
        assert response.status_code in [201, 202]

    def xpi_filepath(self, addon, version):
        return os.path.join(
            'src', 'olympia', 'signing', 'fixtures',
            '{addon}-{version}.xpi'.format(addon=addon, version=version))

    def request(self, method='PUT', url=None, version='3.0',
                addon='@upload-version', filename=None):
        if filename is None:
            filename = self.xpi_filepath(addon, version)
        if url is None:
            url = self.url(addon, version)
        with open(filename) as upload:
            data = {'upload': upload}
            if method == 'POST' and version:
                data['version'] = version

            return getattr(self.client, method.lower())(
                url, data,
                HTTP_AUTHORIZATION=self.authorization())

    def make_admin(self, user):
        admin_group = Group.objects.create(name='Admin', rules='*:*')
        GroupUser.objects.create(group=admin_group, user=user)


class TestUploadVersion(BaseUploadVersionCase):

    def test_not_authenticated(self):
        # Use self.client.put so that we don't add the authorization header.
        response = self.client.put(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    @override_settings(READ_ONLY=True)
    def test_read_only_mode(self):
        response = self.request('PUT', self.url(self.guid, '12.5'))
        assert response.status_code == 503
        assert 'website maintenance' in response.data['error']

    def test_addon_does_not_exist(self):
        guid = '@create-version'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request('PUT', addon=guid, version='1.0')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert not addon.is_listed
        assert addon.status == amo.STATUS_LITE
        self.auto_sign_version.assert_called_with(
            addon.latest_version, is_beta=False)

    def test_user_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_admin_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        self.make_admin(self.user)
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_version_does_not_match_manifest_file(self):
        response = self.request('PUT', self.url(self.guid, '2.5'))
        assert response.status_code == 400
        assert response.data['error'] == (
            'Version does not match the manifest file.')

    def test_version_already_exists(self):
        response = self.request(
            'PUT', self.url(self.guid, '2.1.072'), version='2.1.072')
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

    @mock.patch('olympia.devhub.views.Version.from_upload')
    def test_no_version_yet(self, from_upload):
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_added(self):
        assert Addon.objects.get(guid=self.guid).status == amo.STATUS_PUBLIC
        qs = Version.objects.filter(addon__guid=self.guid, version='3.0')
        assert not qs.exists()

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == '3.0'
        assert version.statuses[0][1] == amo.STATUS_UNREVIEWED
        assert version.addon.status == amo.STATUS_PUBLIC
        self.auto_sign_version.assert_called_with(version, is_beta=False)

    def test_version_already_uploaded(self):
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

    def test_version_failed_review(self):
        self.create_version('3.0')
        version = Version.objects.get(addon__guid=self.guid, version='3.0')
        version.update(reviewed=datetime.today())
        version.files.get().update(reviewed=datetime.today(),
                                   status=amo.STATUS_DISABLED)

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'

        # Verify that you can check the status after upload (#953).
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_added_is_experiment(self):
        self.grant_permission(self.user, 'Experiments:submit')
        guid = 'experiment@xpi'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.1',
            filename='src/olympia/files/fixtures/files/experiment.xpi')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert not addon.is_listed
        assert addon.status == amo.STATUS_LITE
        self.auto_sign_version.assert_called_with(
            addon.latest_version, is_beta=False)

    def test_version_added_is_experiment_reject_no_perm(self):
        guid = 'experiment@xpi'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            addon=guid, version='0.1',
            filename='src/olympia/files/fixtures/files/experiment.xpi')
        assert response.status_code == 400
        assert response.data['error'] == (
            'You cannot submit this type of add-on')

    def test_version_is_beta_unlisted(self):
        Addon.objects.get(guid=self.guid).update(
            status=amo.STATUS_LITE, is_listed=False)
        version_string = '4.0-beta1'
        qs = Version.objects.filter(
            addon__guid=self.guid, version=version_string)
        assert not qs.exists()

        response = self.request(
            'PUT',
            self.url(self.guid, version_string), version=version_string)
        assert response.status_code == 202
        assert 'processed' in response.data

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == version_string
        assert version.statuses[0][1] == amo.STATUS_UNREVIEWED
        assert version.addon.status == amo.STATUS_LITE
        assert not version.is_beta
        self.auto_sign_version.assert_called_with(version, is_beta=False)

    def test_version_is_beta(self):
        assert Addon.objects.get(guid=self.guid).status == amo.STATUS_PUBLIC
        version_string = '4.0-beta1'
        qs = Version.objects.filter(
            addon__guid=self.guid, version=version_string)
        assert not qs.exists()

        response = self.request(
            'PUT',
            self.url(self.guid, version_string), version=version_string)
        assert response.status_code == 202
        assert 'processed' in response.data

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == version_string
        assert version.statuses[0][1] == amo.STATUS_BETA
        assert version.addon.status == amo.STATUS_PUBLIC
        assert version.is_beta
        self.auto_sign_version.assert_called_with(version, is_beta=True)


class TestUploadVersionWebextension(BaseUploadVersionCase):
    def setUp(self):
        super(TestUploadVersionWebextension, self).setUp()
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='*')

        validate_patcher = mock.patch('validator.validate.validate')
        run_validator = validate_patcher.start()
        run_validator.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        self.addCleanup(validate_patcher.stop)

    def test_addon_does_not_exist_webextension(self):
        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@create-webextension',
            version='1.0')
        assert response.status_code == 201

        guid = response.data['guid']
        addon = Addon.unfiltered.get(guid=guid)

        assert addon.guid is not None
        assert addon.guid != self.guid

        version = Version.objects.get(addon__guid=guid, version='1.0')
        assert version.files.all()[0].is_webextension is True
        assert addon.has_author(self.user)
        assert not addon.is_listed
        assert addon.status == amo.STATUS_LITE
        self.auto_sign_version.assert_called_with(
            addon.latest_version, is_beta=False)

    def test_optional_id_not_allowed_for_regular_addon(self):
        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@create-version-no-id',
            version='1.0')
        assert response.status_code == 400

    def test_webextension_reuse_guid(self):
        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@create-webextension-with-guid',
            version='1.0')

        guid = response.data['guid']
        assert guid == '@webextension-with-guid'

        addon = Addon.unfiltered.get(guid=guid)
        assert addon.guid == '@webextension-with-guid'

    def test_webextension_reuse_guid_but_only_create(self):
        # Uploading the same version with the same id fails. People
        # have to use the regular `PUT` endpoint for that.
        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@create-webextension-with-guid',
            version='1.0')
        assert response.status_code == 201

        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@create-webextension-with-guid',
            version='1.0')
        assert response.status_code == 400
        assert response.data['error'] == 'Duplicate add-on ID found.'

    def test_webextension_optional_version(self):
        # Uploading the same version with the same id fails. People
        # have to use the regular `PUT` endpoint for that.
        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@create-webextension-with-guid-and-version',
            version='99.0')
        assert response.status_code == 201
        assert (
            response.data['guid'] ==
            '@create-webextension-with-guid-and-version')
        assert response.data['version'] == '99.0'

    def test_webextension_resolve_translations(self):
        fname = (
            'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi')

        response = self.request(
            'POST',
            url=reverse('signing.version'),
            addon='@notify-link-clicks-i18n',
            version='1.0',
            filename=fname)
        assert response.status_code == 201

        addon = Addon.unfiltered.get(guid=response.data['guid'])

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'
        assert addon.name == 'Notify link clicks i18n'
        assert addon.summary == (
            'Shows a notification when the user clicks on links.')

        translation.activate('de')
        addon.reload()
        assert addon.name == 'Meine Beispielerweiterung'
        assert addon.summary == u'Benachrichtigt den Benutzer über Linkklicks'


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
        self.create_version('3.0')
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this addon.'

    def test_admin_can_view(self):
        self.create_version('3.0')
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.make_admin(self.user)
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

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
        with mock.patch('olympia.devhub.tasks.Version.from_upload'):
            self.create_version('3.0')
        upload = FileUpload.objects.latest()
        upload.update(created=datetime.today() - timedelta(hours=1))

        self.create_version('3.0')
        newer_upload = FileUpload.objects.latest()
        assert newer_upload != upload

        response = self.get(self.url(self.guid, '3.0', upload.uuid))
        assert response.status_code == 200
        # For backwards-compatibility reasons, we return the uuid as "pk".
        assert response.data['pk'] == upload.uuid
        assert 'processed' in response.data

    def test_version_exists_with_pk_not_owner(self):
        orig_user, orig_api_key = self.user, self.api_key

        # This will create a version for the add-on with guid @create-version
        # using a new user.
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now())
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.request('PUT', addon='@create-version', version='1.0')
        assert response.status_code == 201
        upload = FileUpload.objects.latest()

        # Check that the user that created the upload can access it properly.
        response = self.get(self.url('@create-version', '1.0', upload.uuid))
        assert response.status_code == 200
        assert 'processed' in response.data

        # This will create a version for the add-on from the fixture with the
        # regular fixture user.
        self.user, self.api_key = orig_user, orig_api_key
        self.create_version('3.0')

        # Check that we can't access the FileUpload by uuid even if we pass in
        # an add-on and version that we own if we don't own the FileUpload.
        response = self.get(self.url(self.guid, '3.0', upload.uuid))
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


class TestSignedFile(SigningAPITestCase):

    def setUp(self):
        super(TestSignedFile, self).setUp()
        self.file_ = self.create_file()

    def url(self):
        return reverse('signing.file', args=[self.file_.pk])

    def create_file(self):
        addon = Addon.objects.create(name='thing', is_listed=False)
        addon.save()
        AddonUser.objects.create(user=self.user, addon=addon)
        version = Version.objects.create(addon=addon)
        return File.objects.create(version=version)

    def test_can_download_once_authenticated(self):
        response = self.get(self.url())
        assert response.status_code == 302
        assert response['X-Target-Digest'] == self.file_.hash

    def test_cannot_download_without_authentication(self):
        response = self.client.get(self.url())  # no auth
        assert response.status_code == 401

    def test_api_relies_on_version_downloader(self):
        with mock.patch('olympia.versions.views.download_file') as df:
            df.return_value = Response({})
            self.get(self.url())
        assert df.called is True
        assert df.call_args[0][0].user == self.user
        assert df.call_args[0][1] == str(self.file_.pk)
