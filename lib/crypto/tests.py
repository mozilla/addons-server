# -*- coding: utf-8 -*-
import json
import os
import shutil
import zipfile

from django.conf import settings  # For mocking.
from django.core.files.storage import default_storage as storage

import jwt
import mock
from nose.tools import eq_, ok_, raises
from requests import Timeout

import amo.tests
from lib.crypto import packaged
from lib.crypto.receipt import crack, sign, SigningError
from versions.models import Version


def mock_sign(version_id, reviewer=False):
    """
    This is a mock for using in tests, where we really don't want to be
    actually signing the addons. This just copies the file over and returns
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


@mock.patch('lib.crypto.receipt.requests.post')
@mock.patch.object(settings, 'SIGNING_SERVER', 'http://localhost')
class TestReceipt(amo.tests.TestCase):
    def get_response(self, code):
        return mock.Mock(status_code=code,
                         content=json.dumps({'receipt': ''}))

    def test_called(self, mock_post):
        mock_post.return_value = self.get_response(200)
        sign('my-receipt')
        eq_(mock_post.call_args[1]['data'], 'my-receipt')

    def test_some_unicode(self, mock_post):
        mock_post.return_value = self.get_response(200)
        sign({'name': u'Вагиф Сәмәдоғлу'})

    def test_good(self, req):
        req.return_value = self.get_response(200)
        sign('x')

    @raises(SigningError)
    def test_timeout(self, req):
        req.side_effect = Timeout
        req.return_value = self.get_response(200)
        sign('x')

    @raises(SigningError)
    def test_error(self, req):
        req.return_value = self.get_response(403)
        sign('x')

    @raises(SigningError)
    def test_other(self, req):
        req.return_value = self.get_response(206)
        sign('x')


class TestCrack(amo.tests.TestCase):
    def test_crack(self):
        eq_(crack(jwt.encode('foo', 'x')), [u'foo'])

    def test_crack_mulitple(self):
        eq_(crack('~'.join([jwt.encode('foo', 'x'), jwt.encode('bar', 'y')])),
            [u'foo', u'bar'])


@mock.patch('lib.crypto.packaged.os.unlink', new=mock.Mock)
class TestPackaged(amo.tests.TestCase):
    def setUp(self):
        super(TestPackaged, self).setUp()

        # Change addon file name
        self.addon = amo.tests.addon_factory()
        self.addon.update(guid='xxxxx')
        self.version = self.addon.current_version
        self.file1 = self.version.all_files[0]
        self.file1.update(filename='addon-a.xpi')

        self.file2 = amo.tests.file_factory(version=self.version)
        self.file2.update(filename='addon-b.xpi')

        # Add actual file to addons
        if not os.path.exists(os.path.dirname(self.file1.file_path)):
            os.makedirs(os.path.dirname(self.file1.file_path))

        for f in (self.file1, self.file2):
            fp = zipfile.ZipFile(f.file_path, 'w')
            fp.writestr('install.rdf', '<?xml version="1.0"?><RDF></RDF>')
            fp.close()

    def tearDown(self):
        for f in (self.file1, self.file2):
            for path in (
                    f.file_path, f.signed_file_path,
                    f.signed_reviewer_file_path):
                if os.path.exists(path):
                    os.unlink(path)

    @raises(packaged.SigningError)
    def test_no_file(self):
        [f.delete() for f in self.addon.current_version.all_files]
        packaged.sign(self.version.pk)

    @raises(packaged.SigningError)
    def test_non_xpi(self):
        self.file1.update(filename='foo.txt')
        packaged._sign_file(
            self.version.pk, self.addon,
            self.file1, False, False)

    @mock.patch('lib.crypto.packaged.sign_addon')
    def test_already_exists(self, sign_addon):
        with (storage.open(self.file1.signed_file_path, 'w') and
                storage.open(self.file2.signed_file_path, 'w')):
            assert packaged.sign(self.version.pk)
            assert not sign_addon.called

    @mock.patch('lib.crypto.packaged.sign_addon')
    def test_resign_already_exists(self, sign_addon):
        storage.open(self.file1.signed_file_path, 'w')
        storage.open(self.file2.signed_file_path, 'w')
        packaged.sign(self.version.pk, resign=True)
        assert sign_addon.called

    @mock.patch('lib.crypto.packaged.sign_addon')
    def test_sign_consumer(self, sign_addon):
        file_list = packaged.sign(self.version.pk)
        assert sign_addon.called
        ids = json.loads(sign_addon.call_args[0][2])
        eq_(ids['id'], self.addon.guid)
        eq_(ids['version'], self.version.pk)

        file_list = dict(file_list)
        eq_(file_list[self.file1.pk], self.file1.signed_file_path)
        eq_(file_list[self.file2.pk], self.file2.signed_file_path)

    @mock.patch('lib.crypto.packaged.sign_addon')
    def test_sign_reviewer(self, sign_addon):
        file_list = packaged.sign(self.version.pk, reviewer=True)
        assert sign_addon.called
        ids = json.loads(sign_addon.call_args[0][2])
        eq_(ids['id'], 'reviewer-{guid}-{version_id}'.format(
            guid=self.addon.guid, version_id=self.version.pk))
        eq_(ids['version'], self.version.pk)

        file_list = dict(file_list)
        eq_(file_list[self.file1.pk], self.file1.signed_reviewer_file_path)
        eq_(file_list[self.file2.pk], self.file2.signed_reviewer_file_path)

    @raises(ValueError)
    def test_server_active(self):
        with self.settings(SIGNING_SERVER_ACTIVE=True):
            packaged.sign(self.version.pk)

    @raises(ValueError)
    def test_reviewer_server_active(self):
        with self.settings(SIGNING_REVIEWER_SERVER_ACTIVE=True):
            packaged.sign(self.version.pk, reviewer=True)

    @mock.patch('lib.crypto.packaged._no_sign')
    def test_server_inactive(self, _no_sign):
        with self.settings(SIGNING_SERVER_ACTIVE=False):
            packaged.sign(self.version.pk)
        assert _no_sign.called

    @mock.patch('lib.crypto.packaged._no_sign')
    def test_reviewer_server_inactive(self, _no_sign):
        with self.settings(SIGNING_REVIEWER_SERVER_ACTIVE=False):
            packaged.sign(self.version.pk, reviewer=True)
        assert _no_sign.called

    def test_server_endpoint(self):
        with self.settings(SIGNING_SERVER_ACTIVE=True,
                           SIGNING_SERVER='http://sign.me',
                           SIGNING_REVIEWER_SERVER='http://review.me'):
            endpoint = packaged._get_endpoint()
        ok_(endpoint.startswith('http://sign.me'),
            'Unexpected endpoint returned.')

    def test_server_reviewer_endpoint(self):
        with self.settings(SIGNING_REVIEWER_SERVER_ACTIVE=True,
                           SIGNING_SERVER='http://sign.me',
                           SIGNING_REVIEWER_SERVER='http://review.me'):
            endpoint = packaged._get_endpoint(reviewer=True)
        ok_(endpoint.startswith('http://review.me'),
            'Unexpected endpoint returned.')

    @mock.patch.object(packaged, '_get_endpoint', lambda _: '/fake/url/')
    @mock.patch('requests.post')
    def test_inject_ids(self, post):
        """
        Checks correct signing of a package using fake data
        as returned by Trunion
        """
        post().status_code = 200
        post().content = '{"zigbert.rsa": ""}'
        packaged.sign(self.version.pk)
        zf = zipfile.ZipFile(self.file1.signed_file_path, mode='r')
        ids_data = zf.read('META-INF/ids.json')
        eq_(sorted(json.loads(ids_data).keys()), ['id', 'version'])
