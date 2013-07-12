import amo.tests
from mkt.features.api import AppFeaturesSerializer


class TestAppFeaturesSerializer(amo.tests.TestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()
        self.serializer = AppFeaturesSerializer()

    def _test_features(self, true_features):
        features = self.app.current_version.features
        data = self.serializer.to_native(features)
        self.assertSetEqual(['has_' + i for i in data], true_features)

    def test_all_false(self):
        self._test_features([])

    def test_one_true(self):
        features = {'has_apps': True}
        self.app.current_version.features.update(**features)
        self._test_features(features.keys())

    def test_several_true(self):
        features = {'has_apps': True, 'has_video_webm': True}
        self.app.current_version.features.update(**features)
        self._test_features(features.keys())
