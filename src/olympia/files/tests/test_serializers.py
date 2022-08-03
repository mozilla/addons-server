import json

from django.conf import settings

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from olympia.amo.tests import TestCase
from olympia.amo.reverse import reverse

from ..models import FileUpload
from ..serializers import FileUploadSerializer


class TestFileUploadSerializer(TestCase):
    def setUp(self):
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = api_settings.DEFAULT_VERSIONING_CLASS()
        self.request.version = api_version

    def test_basic(self):
        file_upload = FileUpload(version='123', channel=amo.CHANNEL_UNLISTED)
        data = FileUploadSerializer(
            instance=file_upload, context={'request': self.request}
        ).data
        assert data == {
            'uuid': file_upload.uuid.hex,
            'channel': 'unlisted',
            'processed': False,
            'submitted': False,
            'url': settings.EXTERNAL_SITE_URL
            + reverse(
                'v5:addon-upload-detail',
                args=[file_upload.uuid.hex],
            ),
            'valid': False,
            'validation': None,
            'version': '123',
        }

        file_upload.update(
            channel=amo.CHANNEL_LISTED,
            validation=json.dumps([{'something': 'happened'}]),
        )
        data = FileUploadSerializer(
            instance=file_upload, context={'request': self.request}
        ).data
        assert data['channel'] == 'listed'
        assert data['validation'] == [{'something': 'happened'}]
