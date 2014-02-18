# -*- coding: utf-8 -*-
import hashlib
import json
import zipfile

from django.core.files.storage import default_storage as storage

import mock
from nose.tools import eq_

import amo
import amo.tests

from mkt.webapps.models import Webapp
from mkt.site.fixtures import fixture


class TestPackagedManifest(amo.tests.TestCase):
    fixtures = ['base/users'] + fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        # Create a fake package to go along with the app.
        latest_file = self.app.get_latest_file()
        with storage.open(latest_file.file_path,
                          mode='w') as package:
            test_package = zipfile.ZipFile(package, 'w')
            test_package.writestr('manifest.webapp', 'foobar')
            test_package.close()
            latest_file.update(hash=latest_file.generate_hash())

        self.url = self.app.get_manifest_url()

    def tearDown(self):
        storage.delete(self.app.get_latest_file().file_path)

    def get_digest_from_manifest(self, manifest=None):
        if manifest is None:
            manifest = self._mocked_json()
        elif not isinstance(manifest, (str, unicode)):
            manifest = json.dumps(manifest)

        hash_ = hashlib.sha256()
        hash_.update(manifest)
        hash_.update(self.app.get_latest_file().hash)
        return hash_.hexdigest()

    def _mocked_json(self):
        data = {
            u'name': u'Packaged App √',
            u'version': u'1.0',
            u'size': 123456,
            u'release_notes': u'Bug fixes',
            u'packaged_path': u'/path/to/file.zip',
        }
        return json.dumps(data)

    def login_as_reviewer(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def login_as_author(self):
        self.client.logout()
        user = self.app.authors.all()[0]
        self.app.addonuser_set.create(user=user)
        assert self.client.login(username=user.email, password='password')

    def test_non_packaged(self):
        self.app.update(is_packaged=False)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_disabled_by_user(self):
        self.app.update(disabled_by_user=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_app_public(self, _mock):
        _mock.return_value = self._mocked_json()
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'],
            'application/x-web-app-manifest+json; charset=utf-8')
        eq_(res['ETag'], '"%s"' % self.get_digest_from_manifest())

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_etag_updates(self, _mock):
        _mock.return_value = self._mocked_json()

        # Get the minifest with the first simulated package.
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'],
            'application/x-web-app-manifest+json; charset=utf-8')

        first_etag = res['ETag']

        # Write a new value to the packaged app.
        latest_file = self.app.get_latest_file()
        with storage.open(latest_file.file_path,
                          mode='w') as package:
            test_package = zipfile.ZipFile(package, 'w')
            test_package.writestr('manifest.webapp', 'poop')
            test_package.close()
            latest_file.update(hash=latest_file.generate_hash())

        # Get the minifest with the second simulated package.
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'],
            'application/x-web-app-manifest+json; charset=utf-8')

        second_etag = res['ETag']

        self.assertNotEqual(first_etag, second_etag)

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_conditional_get(self, _mock):
        _mock.return_value = self._mocked_json()
        etag = self.get_digest_from_manifest()
        res = self.client.get(self.url, HTTP_IF_NONE_MATCH='%s' % etag)
        eq_(res.content, '')
        eq_(res.status_code, 304)

    def test_app_pending(self):
        self.app.update(status=amo.STATUS_PENDING)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_app_pending_reviewer(self):
        self.login_as_reviewer()
        self.app.update(status=amo.STATUS_PENDING)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_app_pending_author(self):
        self.login_as_author()
        self.app.update(status=amo.STATUS_PENDING)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_logged_out(self, _mock):
        _mock.return_value = self._mocked_json()
        self.client.logout()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res['Content-type'],
            'application/x-web-app-manifest+json; charset=utf-8')
