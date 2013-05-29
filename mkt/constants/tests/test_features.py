from nose.tools import eq_, ok_

from django.conf import settings

import amo.tests
from mkt.constants.features import FeatureProfile


class TestFeatureProfile(amo.tests.TestCase):

    def setUp(self):
        self.binary = '10001000000000010001000000000000'
        self.signature = '88011000.32.%s' % settings.APP_FEATURES_VERSION
        self.truths = ['apps', 'proximity', 'light_events', 'vibrate']

    def _test_profile(self, profile):
        eq_(profile.to_binary(), self.binary)
        eq_(profile.to_signature(), self.signature)
        for k, v in profile.iteritems():
            if v:
                ok_(k in self.truths)
            else:
                ok_(k not in self.truths)

    def test_from_binary(self):
        profile = FeatureProfile.from_binary(self.binary)
        self._test_profile(profile)

    def test_from_signature(self):
        profile = FeatureProfile.from_signature(self.signature)
        self._test_profile(profile)

    def _test_kwargs(self, prefix, only_true):
        profile = FeatureProfile.from_binary(self.binary)
        kwargs = profile.to_kwargs(prefix=prefix, only_true=only_true)

        ok_(all([k.startswith(prefix) for k in kwargs.keys()]))
        eq_(kwargs.values().count(True), self.binary.count('1'))
        if only_true:
            eq_(kwargs.values().count(False), 0)
        else:
            eq_(kwargs.values().count(False), self.binary.count('0'))

    def test_to_kwargs(self):
        self._test_kwargs('', True)
        self._test_kwargs('', False)
        self._test_kwargs('prefix_', True)
        self._test_kwargs('prefix_', False)

