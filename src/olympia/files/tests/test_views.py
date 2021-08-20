import os

from django.conf import settings
from django.test.utils import override_settings
from django.urls import reverse

from olympia import amo
from olympia.amo.tests import (
    APITestClient,
    JWTAPITestClient,
    reverse_ns,
    TestCase,
    user_factory,
)

from .test_models import UploadMixin
from ..models import FileUpload


files_fixtures = 'src/olympia/files/fixtures/files/'
unicode_filenames = 'src/olympia/files/fixtures/files/unicode-filenames.xpi'
not_binary = 'install.js'
binary = 'dictionaries/ar.dic'


class TestServeFileUpload(UploadMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.url = reverse('files.serve_file_upload', args=[self.upload.uuid.hex])

    def test_returns_error_when_no_access_token(self):
        resp = self.client.get(self.url)

        assert resp.status_code == 403

    def test_returns_error_when_access_token_is_invalid(self):
        resp = self.client.get(f'{self.url}?access_token=nope')

        assert resp.status_code == 403

    def test_get(self):
        resp = self.client.get(self.upload.get_authenticated_download_url())

        assert resp.status_code == 200
        assert resp['content-type'] == 'application/octet-stream'
        assert resp[settings.XSENDFILE_HEADER] == self.upload.path

    def test_returns_410_when_upload_path_is_falsey(self):
        self.upload.path = ''
        self.upload.save()

        resp = self.client.get(self.upload.get_authenticated_download_url())

        assert resp.status_code == 410


class FileUploadTestMixin:
    def setUp(self):
        super().setUp()
        self.list_url = reverse_ns('addon-submission-list', api_version='v5')
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        # Add a file upload
        self.upload = FileUpload.objects.create(user=self.user)
        # Add some other ones from other users
        self.other_user_upload = FileUpload.objects.create(user=user_factory())
        FileUpload.objects.create()

        self.detail_url = reverse_ns(
            'addon-submission-detail',
            kwargs={'uuid': self.upload.uuid.hex},
            api_version='v5',
        )
        self.client.login_api(self.user)

    def _xpi_filepath(self, guid, version):
        return os.path.join(
            'src',
            'olympia',
            'signing',
            'fixtures',
            f'{guid}-{version}.xpi',
        )

    def test_not_authenticated(self):
        self.client.logout_api()
        response = self.client.get(
            self.list_url,
        )
        assert response.status_code == 401

    def test_no_developer_agreement(self):
        self.user.update(read_dev_agreement=None)
        filepath = self._xpi_filepath('@upload-version', '3.0')

        with open(filepath, 'rb') as upload:
            data = {
                'upload': upload,
                'channel': 'listed',
            }

            response = self.client.post(
                self.list_url,
                data,
                format='multipart',
                REMOTE_ADDR='127.0.3.1',
            )
        assert response.status_code in [401, 403]  # JWT auth is a 401; web auth is 403

    def test_create(self):
        upload_count_before = FileUpload.objects.count()
        filepath = self._xpi_filepath('@upload-version', '3.0')

        with open(filepath, 'rb') as upload:
            data = {
                'upload': upload,
                'channel': 'listed',
            }

            response = self.client.post(
                self.list_url,
                data,
                format='multipart',
                REMOTE_ADDR='127.0.3.1',
            )

        assert response.status_code == 201

        assert FileUpload.objects.count() != upload_count_before
        upload = FileUpload.objects.last()

        assert upload.name == f'{upload.uuid.hex}_@upload-version-3.0.xpi'
        assert upload.source == amo.UPLOAD_SOURCE_ADDON_API
        assert upload.user == self.user
        assert upload.version == '3.0'
        assert upload.ip_address == '127.0.3.1'

        data = response.json()
        assert data['uuid'] == upload.uuid.hex

    def test_list(self):
        response = self.client.get(
            self.list_url,
        )
        data = response.json()['results']
        assert len(data) == 1  # only the users own uploads
        assert data[0]['uuid'] == self.upload.uuid.hex
        assert data[0]['url'] == self.detail_url

    def test_api_unavailable(self):
        with override_settings(DRF_API_GATES={'v5': []}):
            response = self.client.get(
                self.list_url,
            )
        assert response.status_code == 403

    def test_retrieve(self):
        response = self.client.get(self.detail_url)
        data = response.json()
        assert data['uuid'] == self.upload.uuid.hex
        assert data['url'] == self.detail_url

    def test_cannot_retrieve_other_uploads(self):
        detail_url = reverse_ns(
            'addon-submission-detail',
            kwargs={'uuid': self.other_user_upload.uuid.hex},
            api_version='v5',
        )
        response = self.client.get(
            detail_url,
        )
        assert response.status_code == 404


class TestFileUploadViewSetJWTAuth(FileUploadTestMixin, TestCase):
    client_class = JWTAPITestClient


class TestFileUploadViewSetWebTokenAuth(FileUploadTestMixin, TestCase):
    client_class = APITestClient
