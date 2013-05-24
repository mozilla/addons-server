# -*- coding: utf-8 -*-
import json
import os
import shutil

from django.conf import settings  # For mocking.
from django.core.files.storage import default_storage as storage

import jwt
import mock
from nose.tools import eq_, raises

import amo.tests
from lib.crypto import packaged
from lib.crypto.receipt import crack, sign, SigningError
from mkt.webapps.models import Webapp
from versions.models import Version


def mock_sign(version_id, reviewer=False):
    """
    This is a mock for using in tests, where we really don't want to be
    actually signing the apps. This just copies the file over and returns
    the path. It doesn't have much error checking.
    """
    version = Version.objects.get(pk=version_id)
    file_obj = version.all_files[0]
    path = (file_obj.signed_reviewer_file_path if reviewer else
            file_obj.signed_file_path)
    try:
        os.makedirs(os.path.dirname(path))
    except OSError:
        pass
    shutil.copyfile(file_obj.file_path, path)
    return path


@mock.patch('lib.metrics.urllib2.urlopen')
@mock.patch.object(settings, 'SIGNING_SERVER', 'http://localhost')
class TestReceipt(amo.tests.TestCase):

    def test_called(self, urlopen):
        urlopen.return_value = self.get_response(200)
        sign('my-receipt')
        eq_(urlopen.call_args[0][0].data, 'my-receipt')

    def test_some_unicode(self, urlopen):
        urlopen.return_value = self.get_response(200)
        sign({'name': u'Вагиф Сәмәдоғлу'})

    def get_response(self, code):
        response = mock.Mock()
        response.getcode = mock.Mock()
        response.getcode.return_value = code
        response.read.return_value = json.dumps({'receipt': ''})
        return response

    @raises(SigningError)
    def test_error(self, urlopen):
        urlopen.return_value = self.get_response(403)
        sign('x')

    def test_good(self, urlopen):
        urlopen.return_value = self.get_response(200)
        sign('x')

    @raises(SigningError)
    def test_other(self, urlopen):
        urlopen.return_value = self.get_response(206)
        sign('x')


class TestCrack(amo.tests.TestCase):

    def test_crack(self):
        eq_(crack(jwt.encode('foo', 'x')), [u'foo'])

    def test_crack_mulitple(self):
        eq_(crack('~'.join([jwt.encode('foo', 'x'), jwt.encode('bar', 'y')])),
            [u'foo', u'bar'])


class PackagedApp(amo.tests.TestCase, amo.tests.AMOPaths):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        self.version = self.app.current_version
        self.file = self.version.all_files[0]
        self.file.update(filename='mozball.zip')

    def setup_files(self):
        # Clean out any left over stuff.
        storage.delete(self.file.signed_file_path)
        storage.delete(self.file.signed_reviewer_file_path)

        # Make sure the source file is there.
        if not storage.exists(self.file.file_path):
            try:
                # We don't care if these dirs exist.
                os.makedirs(os.path.dirname(self.file.file_path))
            except OSError:
                pass
            shutil.copyfile(self.packaged_app_path('mozball.zip'),
                            self.file.file_path)


class TestPackaged(PackagedApp, amo.tests.TestCase):

    def setUp(self):
        super(TestPackaged, self).setUp()
        self.setup_files()

    @raises(packaged.SigningError)
    def test_not_app(self):
        self.app.update(type=amo.ADDON_EXTENSION)
        packaged.sign(self.version.pk)

    @raises(packaged.SigningError)
    def test_not_packaged(self):
        self.app.update(is_packaged=False)
        packaged.sign(self.version.pk)

    @raises(packaged.SigningError)
    def test_no_file(self):
        [f.delete() for f in self.app.current_version.all_files]
        packaged.sign(self.version.pk)

    @mock.patch('lib.crypto.packaged.sign_app')
    def test_already_exists(self, sign_app):
        storage.open(self.file.signed_file_path, 'w')
        assert packaged.sign(self.version.pk)
        assert not sign_app.called

    @mock.patch('lib.crypto.packaged.sign_app')
    def test_resign_already_exists(self, sign_app):
        storage.open(self.file.signed_file_path, 'w')
        packaged.sign(self.version.pk, resign=True)
        assert sign_app.called

    @raises(ValueError)
    def test_server_active(self):
        with self.settings(SIGNED_APPS_SERVER_ACTIVE=True):
            packaged.sign(self.version.pk)

    @raises(ValueError)
    def test_reviewer_server_active(self):
        with self.settings(SIGNED_APPS_REVIEWER_SERVER_ACTIVE=True):
            packaged.sign(self.version.pk, reviewer=True)

    @mock.patch('lib.crypto.packaged._no_sign')
    def test_server_inactive(self, _no_sign):
        with self.settings(SIGNED_APPS_SERVER_ACTIVE=False):
            packaged.sign(self.version.pk)
        assert _no_sign.called

    @mock.patch('lib.crypto.packaged._no_sign')
    def test_reviewer_server_inactive(self, _no_sign):
        with self.settings(SIGNED_APPS_REVIEWER_SERVER_ACTIVE=False):
            packaged.sign(self.version.pk, reviewer=True)
        assert _no_sign.called

    def test_server_endpoint(self):
        with self.settings(SIGNED_APPS_SERVER_ACTIVE=True,
                           SIGNED_APPS_SERVER='http://sign.me',
                           SIGNED_APPS_REVIEWER_SERVER='http://review.me'):
            endpoint = packaged._get_endpoint()
        assert endpoint.startswith('http://sign.me'), (
            'Unexpected endpoint returned.')

    def test_server_reviewer_endpoint(self):
        with self.settings(SIGNED_APPS_REVIEWER_SERVER_ACTIVE=True,
                           SIGNED_APPS_SERVER='http://sign.me',
                           SIGNED_APPS_REVIEWER_SERVER='http://review.me'):
            endpoint = packaged._get_endpoint(reviewer=True)
        assert endpoint.startswith('http://review.me'), (
            'Unexpected endpoint returned.')
