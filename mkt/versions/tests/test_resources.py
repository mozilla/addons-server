from mock import patch
from nose.tools import eq_

from mkt.api.tests.test_oauth import BaseOAuth
from mkt.site.fixtures import fixture
from mkt.versions.resources import VersionResource
from mkt.webapps.models import Webapp
from test_utils import RequestFactory
from versions.models import Version


class TestVersionResource(BaseOAuth):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.request = RequestFactory().get('/')
        self.resource = VersionResource()
        self.version = Version.objects.create(addon=self.app, version='1.0')

    def _get_bundle(self):
        bundle = self.resource.build_bundle(obj=self.version,
                                            request=self.request)
        bundle = self.resource.full_dehydrate(bundle)
        return self.resource.alter_detail_data_to_serialize(self.request,
                                                            bundle)

    def test_version_latest(self):
        bundle = self._get_bundle()
        eq_(bundle.data['name'], '1.0')
        eq_(bundle.data['latest'], True)

    def test_version_not_latest(self):
        new_version = Version.objects.create(addon=self.app, version='1.1')
        with patch.object(self.app, '_latest_version', new_version):
            bundle = self._get_bundle()
            eq_(bundle.data['name'], '1.0')
            eq_(bundle.data['latest'], False)
