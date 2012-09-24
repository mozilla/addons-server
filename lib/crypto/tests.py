# -*- coding: utf8 -*-
import json
import os

from django.conf import settings  # For mocking.
from django.core.files.storage import default_storage as storage

import jwt
import mock
from nose.tools import eq_, raises

import amo.tests
from lib.crypto import packaged
from lib.crypto.receipt import crack, sign, SigningError
from mkt.submit.tests.test_views import BasePackagedAppTest


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


class PackagedApp(BasePackagedAppTest):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(PackagedApp, self).setUp()

    def setup_files(self):
        # Clean out any left over stuff.
        storage.delete(self.file.signed_file_path)
        storage.delete(self.file.signed_reviewer_file_path)

        super(PackagedApp, self).setup_files()


class TestPackaged(PackagedApp, amo.tests.TestCase):

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

    def test_already_exists(self):
        storage.open(self.file.signed_file_path, 'w')
        assert packaged.sign(self.version.pk)

    def test_good(self):
        self.setup_files()
        path = packaged.sign(self.version.pk)
        # TODO: This will change when we actually sign things.
        assert os.stat(path).st_size == (
                os.stat(self.file.file_path).st_size)

    def test_reviewer(self):
        self.setup_files()
        path = packaged.sign(self.version.pk, True)
        assert os.stat(path).st_size == (
                os.stat(self.file.file_path).st_size)
