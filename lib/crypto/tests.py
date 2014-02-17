# -*- coding: utf-8 -*-
import json
import os
import shutil

from django.conf import settings  # For mocking.

import jwt
import mock
from nose.tools import eq_, raises

import amo.tests
from lib.crypto.receipt import crack, sign, SigningError
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


@mock.patch('lib.crypto.receipt.urllib2.urlopen')
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
