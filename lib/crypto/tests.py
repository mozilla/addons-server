# -*- coding: utf8 -*-
import json
import os
import shutil

from django.conf import settings
from django.core.files.storage import default_storage as storage

import jwt
import mock
from nose.tools import eq_, raises

from addons.models import Addon
import amo.tests
from lib.crypto import packaged
from lib.crypto.receipt import crack, sign, SigningError


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


class TestPackaged(amo.tests.AMOPaths, amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.app = Addon.objects.get(pk=337141)
        self.app.update(is_packaged=True)

        self.file = self.app.current_version.all_files[0]
        self.file.update(filename='mozball.zip')
        self.pk = self.app.current_version.pk

    def setup_files(self):
        # Clean out any left over stuff.
        if storage.exists(self.file.signed_file_path):
            storage.delete(self.file.signed_file_path)

        # Make sure the source file is there.
        if not storage.exists(self.file.file_path):
            os.makedirs(os.path.dirname(self.file.file_path))
            shutil.copyfile(self.packaged_app_path('mozball.zip'),
                            self.file.file_path)

    @raises(packaged.SigningError)
    def test_not_app(self):
        self.app.update(type=amo.ADDON_EXTENSION)
        packaged.sign(self.pk)

    @raises(packaged.SigningError)
    def test_not_packaged(self):
        self.app.update(is_packaged=False)
        packaged.sign(self.pk)

    @raises(packaged.SigningError)
    def test_no_file(self):
        [f.delete() for f in self.app.current_version.all_files]
        packaged.sign(self.pk)

    def test_already_exists(self):
        storage.open(self.file.signed_file_path, 'w')
        assert not packaged.sign(self.pk)

    def test_good(self):
        self.setup_files()
        assert packaged.sign(self.pk)
        # TODO: This will change when we actually sign things.
        assert os.stat(self.file.signed_file_path).st_size == (
                os.stat(self.file.file_path).st_size)
