import json

from django.core.urlresolvers import reverse

import mock
from nose.tools import eq_, ok_
from rest_framework.reverse import reverse as rest_reverse

from amo.tests import app_factory, TestCase
from mkt.api.base import get_url
from mkt.api.tests.test_oauth import RestOAuth
from mkt.site.fixtures import fixture
from mkt.versions.api import VersionSerializer
from test_utils import RequestFactory
from versions.models import Version


class TestVersionSerializer(TestCase):
    def setUp(self):
        self.app = app_factory()
        self.features = self.app.current_version.features
        self.serializer = VersionSerializer()

    def native(self, obj=None, **kwargs):
        if not obj:
            obj = self.app.current_version
        obj.update(**kwargs)
        return self.serializer.to_native(obj)

    def test_renamed_fields(self):
        native = self.native()
        removed_keys = self.serializer.Meta.field_rename.keys()
        added_keys = self.serializer.Meta.field_rename.values()
        ok_(all(not k in native for k in removed_keys))
        ok_(all(k in native for k in added_keys))

    def test_addon(self):
        eq_(self.native()['app'], reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': self.app.pk}
        ))

    def test_is_current_version(self):
        old_version = Version.objects.create(addon=self.app, version='0.1')
        ok_(self.native()['is_current_version'])
        ok_(not self.native(obj=old_version)['is_current_version'])

    def test_features(self, **kwargs):
        if kwargs:
            self.features.update(**kwargs)
        native = self.native()
        for key in dir(self.features):
            if key.startswith('has_') and getattr(self.features, key):
                ok_(key.replace('has_', '') in native['features'])

    def test_features_updated(self):
        self.test_features(has_fm=True)


class TestVersionViewSet(RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.app = app_factory()
        self.app_url = get_url('app', self.app.pk)
        self.version = self.app.current_version
        self.request = RequestFactory()

    def test_get(self, version=None, **kwargs):

        if not version:
            version = self.version

        url = rest_reverse('version-detail', kwargs={'pk': version.pk})
        res = self.client.get(url, kwargs)
        data = res.data
        features = data['features']

        eq_(res.status_code, 200)

        # Test values on Version object.
        eq_(data['version'], version.version)
        eq_(data['developer_name'], version.developer_name)
        eq_(data['is_current_version'],
            version == self.app.current_version)
        eq_(data['app'], reverse('api_dispatch_detail', kwargs={
            'resource_name': 'app',
            'api_name': 'apps',
            'pk': self.app.pk}
        ))

        for key in features:
            ok_(getattr(version.features, 'has_' + key))

    def test_get_updated_data(self):
        version = Version.objects.create(addon=self.app, version='1.2')
        version.features.update(has_mp3=True, has_fm=True)
        self.app.update(_latest_version=version, _current_version=version)

        self.test_get()  # Test old version
        self.test_get(version=version)  # Test new version

    @mock.patch('mkt.versions.api.AllowAppOwner.has_object_permission')
    def patch(self, mock_has_permission, features=None, auth=True):
        mock_has_permission.return_value = auth
        data = {
            'features': features or ['fm', 'mp3'],
            'developer_name': "Cee's Vans"
        }
        url = rest_reverse('version-detail', kwargs={'pk': self.version.pk})

        # Uses PUT because Django's test client didn't support PATCH until
        # bug #17797 was resolved.
        res = self.client.put(url, data=json.dumps(data),
                              content_type='application/json')
        return data, res

    def test_patch(self):
        data, res = self.patch()
        eq_(res.status_code, 200)
        self.assertSetEqual(self.version.features.to_keys(),
                            ['has_' + f for f in data['features']])

    def test_patch_bad_features(self):
        data, res = self.patch(features=['bad'])
        eq_(res.status_code, 400)

    def test_patch_no_permission(self):
        data, res = self.patch(auth=False)
        eq_(res.status_code, 403)
