from nose.tools import ok_

from mkt.api.tests.test_oauth import BaseOAuth
from mkt.constants import APP_FEATURES
from mkt.site.fixtures import fixture
from mkt.webapps.api import AppFeaturesSerializer
from mkt.webapps.models import Webapp
from test_utils import RequestFactory


class TestAppFeaturesSerializer(BaseOAuth):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.features = Webapp.objects.get(pk=337141).latest_version.features
        self.request = RequestFactory().get('/')

    def get_native(self, **kwargs):
        self.features.update(**kwargs)
        return AppFeaturesSerializer().to_native(self.features)

    def test_no_features(self):
        native = self.get_native()
        ok_(not native['required'])

    def test_one_feature(self):
        native = self.get_native(has_pay=True)
        self.assertSetEqual(native['required'], ['pay'])

    def test_all_features(self):
        data = dict(('has_' + f.lower(), True) for f in APP_FEATURES)
        native = self.get_native(**data)
        self.assertSetEqual(native['required'],
                            [f.lower() for f in APP_FEATURES])
