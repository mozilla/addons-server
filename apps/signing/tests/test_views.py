import os
from datetime import datetime

from django.core.urlresolvers import reverse

import mock
from rest_framework.test import APITestCase

from addons.models import Addon
from api.tests.test_jwt_auth import JWTAuthTester
from signing.views import VersionView
from users.models import UserProfile
from versions.models import Version


class BaseUploadVersionCase(APITestCase, JWTAuthTester):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.api_key = self.create_api_key(self.user, 'foo')
        self.guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        self.view = VersionView.as_view()

    def url(self, guid, version):
        return reverse('signing.version', args=[guid, version])

    def create_version(self, version):
        self.put(self.url(self.guid, version), version)

    def authorization(self):
        token = self.create_auth_token(self.api_key.user, self.api_key.key,
                                       self.api_key.secret)
        return 'JWT {}'.format(token)

    def xpi_filepath(self, addon, version):
        return os.path.join(
            'apps', 'signing', 'fixtures',
            '{addon}-{version}.xpi'.format(addon=addon, version=version))

    def put(self, url=None, version='3.0', addon='@upload-version'):
        filename = self.xpi_filepath(addon, version)
        if url is None:
            url = self.url(addon, version)
        with open(filename) as upload:
            return self.client.put(url, {'upload': upload},
                                   HTTP_AUTHORIZATION=self.authorization())

    def get(self, url):
        return self.client.get(url, HTTP_AUTHORIZATION=self.authorization())


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
        assert sign_version.called

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

    @mock.patch('devhub.views.auto_sign_version')
    def test_version_added(self, sign_version):
        qs = Version.objects.filter(addon__guid=self.guid, version='3.0')
        assert not qs.exists()

        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == '3.0'
        assert sign_version.called

    def test_version_already_uploaded(self):
        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.put(self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == 'Version already exists.'


class TestCheckVersion(BaseUploadVersionCase):

    def test_not_authenticated(self):
        # Use self.client.get so that we don't add the authorization header.
        response = self.client.get(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    def test_addon_does_not_exist(self):
        response = self.get(self.url('foo', '12.5'))
        assert response.status_code == 404
        assert response.data['error'] == 'Could not find addon.'

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
