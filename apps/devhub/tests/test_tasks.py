import json
import os
import path
import shutil
import socket
import tempfile
import urllib2

from django.conf import settings

import mock
from nose.tools import eq_
from PIL import Image

import amo.tests
from addons.models import Addon
from amo.tests.test_helpers import get_image_path
from files.models import FileUpload
from devhub.tasks import flag_binary, resize_icon, validator, fetch_manifest


def test_resize_icon_shrink():
    """ Image should be shrunk so that the longest side is 32px. """

    resize_size = 32
    final_size = (32, 12)

    _uploader(resize_size, final_size)


def test_resize_icon_enlarge():
    """ Image stays the same, since the new size is bigger than both sides. """

    resize_size = 100
    final_size = (82, 31)

    _uploader(resize_size, final_size)


def test_resize_icon_same():
    """ Image stays the same, since the new size is the same. """

    resize_size = 82
    final_size = (82, 31)

    _uploader(resize_size, final_size)


def test_resize_icon_list():
    """ Resize multiple images at once. """

    resize_size = [32, 82, 100]
    final_size = [(32, 12), (82, 31), (82, 31)]

    _uploader(resize_size, final_size)


def _uploader(resize_size, final_size):
    img = get_image_path('mozilla.png')
    original_size = (82, 31)

    src = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png",
                                      delete=False)

    # resize_icon removes the original
    shutil.copyfile(img, src.name)

    src_image = Image.open(src.name)
    eq_(src_image.size, original_size)

    if isinstance(final_size, list):
        for rsize, fsize in zip(resize_size, final_size):
            dest_name = str(path.path(settings.ADDON_ICONS_PATH) / '1234')

            resize_icon(src.name, dest_name, resize_size)
            dest_image = Image.open("%s-%s.png" % (dest_name, rsize))
            eq_(dest_image.size, fsize)

            if os.path.exists(dest_image.filename):
                os.remove(dest_image.filename)
            assert not os.path.exists(dest_image.filename)
    else:
        dest = tempfile.NamedTemporaryFile(mode='r+w+b', suffix=".png")
        resize_icon(src.name, dest.name, resize_size)
        dest_image = Image.open(dest.name)
        eq_(dest_image.size, final_size)

    assert not os.path.exists(src.name)


class TestValidator(amo.tests.TestCase):

    def setUp(self):
        self.upload = FileUpload.objects.create()
        assert not self.upload.valid

    def get_upload(self):
        return FileUpload.objects.get(pk=self.upload.pk)

    @mock.patch('devhub.tasks.run_validator')
    def test_pass_validation(self, _mock):
        _mock.return_value = '{"errors": 0}'
        validator(self.upload.pk)
        assert self.get_upload().valid

    @mock.patch('devhub.tasks.run_validator')
    def test_fail_validation(self, _mock):
        _mock.return_value = '{"errors": 2}'
        validator(self.upload.pk)
        assert not self.get_upload().valid

    @mock.patch('devhub.tasks.run_validator')
    def test_validation_error(self, _mock):
        _mock.side_effect = Exception
        eq_(self.upload.task_error, None)
        with self.assertRaises(Exception):
            validator(self.upload.pk)
        error = self.get_upload().task_error
        assert error.startswith('Traceback (most recent call last)'), error


class TestFlagBinary(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.addon.update(binary=False)

    @mock.patch('devhub.tasks.run_validator')
    def test_flag_binary(self, _mock):
        _mock.return_value = '{"metadata":{"contains_binary_extension": 1}}'
        flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, True)

    @mock.patch('devhub.tasks.run_validator')
    def test_flag_not_binary(self, _mock):
        _mock.return_value = '{"metadata":{"contains_binary_extension": 0}}'
        flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, False)

    @mock.patch('devhub.tasks.run_validator')
    def test_flag_error(self, _mock):
        _mock.side_effect = RuntimeError()
        flag_binary([self.addon.pk])
        eq_(Addon.objects.get(pk=self.addon.pk).binary, False)


class TestFetchManifest(amo.tests.TestCase):

    def setUp(self):
        self.upload = FileUpload.objects.create()
        self.content_type = 'application/x-web-app-manifest+json'

        patcher = mock.patch('devhub.tasks.urllib2.urlopen')
        self.urlopen_mock = patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch('devhub.tasks.validator')
    def test_success_add_file(self, validator_mock):
        response_mock = mock.Mock()
        response_mock.read.return_value = 'woo'
        response_mock.headers = {'Content-Type': self.content_type}
        self.urlopen_mock.return_value = response_mock

        fetch_manifest('http://xx.com/manifest.json', self.upload.pk)
        upload = FileUpload.objects.get(pk=self.upload.pk)
        eq_(upload.name, 'http://xx.com/manifest.json')
        eq_(open(upload.path).read(), 'woo')

    @mock.patch('devhub.tasks.validator')
    def test_success_call_validator(self, validator_mock):
        response_mock = mock.Mock()
        response_mock.read.return_value = 'woo'
        ct = self.content_type + '; charset=utf-8'
        response_mock.headers = {'Content-Type': ct}
        self.urlopen_mock.return_value = response_mock

        fetch_manifest('http://xx.com/manifest.json', self.upload.pk)
        assert validator_mock.called

    def check_validation(self, msg):
        upload = FileUpload.objects.get(pk=self.upload.pk)
        validation = json.loads(upload.validation)
        eq_(validation['errors'], 1)
        eq_(validation['success'], False)
        eq_(len(validation['messages']), 1)
        eq_(validation['messages'][0], msg)

    def test_connection_error(self):
        reason = socket.gaierror(8, 'nodename nor servname provided')
        self.urlopen_mock.side_effect = urllib2.URLError(reason)
        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation('Could not contact host at "url".')

    def test_url_timeout(self):
        reason = socket.timeout('too slow')
        self.urlopen_mock.side_effect = urllib2.URLError(reason)
        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation('Connection to "url" timed out.')

    def test_other_url_error(self):
        reason = Exception('Some other failure.')
        self.urlopen_mock.side_effect = urllib2.URLError(reason)
        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation('Some other failure.')

    def test_no_content_type(self):
        response_mock = mock.Mock()
        response_mock.read.return_value = 'woo'
        response_mock.headers = {}
        self.urlopen_mock.return_value = response_mock

        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'Your manifest must be served with the HTTP header '
            '"Content-Type: application/x-web-app-manifest+json".')

    def test_bad_content_type(self):
        response_mock = mock.Mock()
        response_mock.read.return_value = 'woo'
        response_mock.headers = {'Content-Type': 'x'}
        self.urlopen_mock.return_value = response_mock

        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation(
            'Your manifest must be served with the HTTP header '
            '"Content-Type: application/x-web-app-manifest+json". We saw "x".')

    def test_response_too_large(self):
        response_mock = mock.Mock()
        content = 'x' * (settings.MAX_WEBAPP_UPLOAD_SIZE + 1)
        response_mock.read.return_value = content
        response_mock.headers = {'Content-Type': self.content_type}
        self.urlopen_mock.return_value = response_mock

        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation('Your manifest must be less than 2097152 bytes.')

    def test_http_error(self):
        self.urlopen_mock.side_effect = urllib2.HTTPError(
            'url', 404, 'Not Found', [], None)
        with self.assertRaises(Exception):
            fetch_manifest('url', self.upload.pk)
        self.check_validation('url responded with 404 (Not Found).')
