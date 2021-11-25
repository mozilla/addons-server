import os
from datetime import timedelta

from django.conf import settings
from django.test.utils import override_settings
from django.urls import reverse

from freezegun import freeze_time

from olympia import amo
from olympia.amo.tests import (
    APITestClient,
    JWTAPITestClient,
    get_random_ip,
    reverse_ns,
    TestCase,
    user_factory,
)

from .test_models import UploadMixin
from ..models import FileUpload
from ..views import FileUploadViewSet


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


class TestFileUploadViewSet(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()
        self.list_url = reverse_ns('addon-upload-list', api_version='v5')
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
        # Add a file upload
        self.upload = FileUpload.objects.create(user=self.user)
        # Add some other ones from other users
        self.other_user_upload = FileUpload.objects.create(user=user_factory())
        FileUpload.objects.create()

        self.detail_url = reverse_ns(
            'addon-upload-detail',
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

    def _create_post(self, channel_name='listed', ip='63.245.208.194'):
        with open(self._xpi_filepath('@upload-version', '3.0'), 'rb') as upload:
            data = {
                'upload': upload,
                'channel': channel_name,
            }

            response = self.client.post(
                self.list_url,
                data,
                format='multipart',
                REMOTE_ADDR=ip,
                HTTP_X_FORWARDED_FOR=f'{ip}, {get_random_ip()}',
            )
        return response

    def test_not_authenticated(self):
        self.client.logout_api()
        response = self.client.get(
            self.list_url,
        )
        assert response.status_code == 401

    def test_no_developer_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self._create_post()
        assert response.status_code in [401, 403]  # JWT auth is a 401; web auth is 403

    def _test_create(self, channel, channel_name):
        upload_count_before = FileUpload.objects.count()

        response = self._create_post(channel_name)
        assert response.status_code == 201

        assert FileUpload.objects.count() == upload_count_before + 1
        upload = FileUpload.objects.last()

        assert upload.name == f'{upload.uuid.hex}_@upload-version-3.0.xpi'
        assert upload.source == amo.UPLOAD_SOURCE_ADDON_API
        assert upload.user == self.user
        assert upload.version == '3.0'
        assert upload.ip_address == '63.245.208.194'
        assert upload.channel == channel

        data = response.json()
        assert data['uuid'] == upload.uuid.hex
        assert data['channel'] == channel_name

    def test_create_listed(self):
        self._test_create(amo.RELEASE_CHANNEL_LISTED, 'listed')

    def test_create_unlisted(self):
        self._test_create(amo.RELEASE_CHANNEL_UNLISTED, 'unlisted')

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
            'addon-upload-detail',
            kwargs={'uuid': self.other_user_upload.uuid.hex},
            api_version='v5',
        )
        response = self.client.get(
            detail_url,
        )
        assert response.status_code == 404

    def test_throttling_ip_burst(self):
        ip = '63.245.208.194'
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _ in range(0, 6):
                self._add_fake_throttling_action(
                    view_class=FileUploadViewSet,
                    url=self.list_url,
                    user=user_factory(),
                    remote_addr=ip,
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self._create_post(ip=ip)
            assert response.status_code == 429, response.content

            # 'Burst' throttling is 1 minute, so 61 seconds later we should be
            # allowed again.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self._create_post(ip=ip)
            assert response.status_code == 201, response.content

    def test_throttling_verb_ip_hourly(self):
        ip = '63.245.208.194'
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _ in range(0, 50):
                self._add_fake_throttling_action(
                    view_class=FileUploadViewSet,
                    url=self.list_url,
                    user=user_factory(),
                    remote_addr=ip,
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self._create_post(ip='63.245.208.194')
            assert response.status_code == 429, response.content

            # One minute later, past the 'burst' throttling period, we're still
            # blocked by the 'hourly' limit.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self._create_post(ip=ip)
            assert response.status_code == 429

            # 'hourly' throttling is 1 hour, so 3601 seconds later we should
            # be allowed again.
            frozen_time.tick(delta=timedelta(seconds=3601))
            response = self._create_post(ip=ip)
            assert response.status_code == 201

    def test_throttling_user_burst(self):
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _ in range(0, 6):
                self._add_fake_throttling_action(
                    view_class=FileUploadViewSet,
                    url=self.list_url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 429, response.content

            # 'Burst' throttling is 1 minute, so 61 seconds later we should be
            # allowed again.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 201, response.content

    def test_throttling_user_hourly(self):
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _ in range(0, 20):
                self._add_fake_throttling_action(
                    view_class=FileUploadViewSet,
                    url=self.list_url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 429, response.content

            # One minute later, past the 'burst' throttling period, we're still
            # blocked by the 'hourly' limit.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 429, response.content

            # 3601 seconds later we should be allowed again.
            frozen_time.tick(delta=timedelta(seconds=3601))
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 201, response.content

    def test_throttling_user_daily(self):
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _ in range(0, 48):
                self._add_fake_throttling_action(
                    view_class=FileUploadViewSet,
                    url=self.list_url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 429, response.content

            # One minute later, past the 'burst' throttling period, we're still
            # blocked by the 'hourly' limit.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 429, response.content

            # After the hourly limit, still blocked.
            frozen_time.tick(delta=timedelta(seconds=3601))
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 429, response.content

            # 86401 seconds later we should be allowed again (24h + 1s).
            frozen_time.tick(delta=timedelta(seconds=86401))
            response = self._create_post(ip=get_random_ip())
            assert response.status_code == 201, response.content


class TestFileUploadViewSetJWTAuth(TestFileUploadViewSet):
    client_class = JWTAPITestClient
