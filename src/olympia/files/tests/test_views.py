# coding=utf-8
from django.conf import settings
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse

from .test_models import UploadTest


files_fixtures = 'src/olympia/files/fixtures/files/'
unicode_filenames = 'src/olympia/files/fixtures/files/unicode-filenames.xpi'
not_binary = 'install.js'
binary = 'dictionaries/ar.dic'


class TestServeFileUpload(UploadTest, TestCase):
    def setUp(self):
        super(TestServeFileUpload, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.url = reverse('files.serve_file_upload',
                           args=[self.upload.uuid.hex])

    def test_returns_error_when_no_access_token(self):
        resp = self.client.get(self.url)

        assert resp.status_code == 403

    def test_returns_error_when_access_token_is_invalid(self):
        resp = self.client.get('{}?access_token=nope'.format(self.url))

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
