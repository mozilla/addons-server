from nose.tools import eq_, ok_

from django.conf import settings

import amo.tests
from mkt.constants.features import APP_FEATURES, FeatureProfile


class TestFeatureProfile(amo.tests.TestCase):

    def setUp(self):
        self.features = 0x88011000
        self.signature = '88011000.32.%s' % settings.APP_FEATURES_VERSION
        self.truths = ['apps', 'proximity', 'light_events', 'vibrate']

    def test_init(self):
        profile = FeatureProfile(**dict((f, True) for f in self.truths))
        eq_(profile.to_signature(), self.signature)
        eq_(profile.to_int(), self.features)

    def _test_profile(self, profile):
        eq_(profile.to_int(), self.features)
        eq_(profile.to_signature(), self.signature)
        for k, v in profile.iteritems():
            if v:
                ok_(k in self.truths, '%s not in truths' % k)
            else:
                ok_(k not in self.truths, '%s is in truths' % k)

    def test_from_int(self):
        profile = FeatureProfile.from_int(self.features)
        self._test_profile(profile)

    def test_from_int_all_false(self):
        self.features = 0
        self.signature = '0.32.%s' % settings.APP_FEATURES_VERSION
        self.truths = []
        self.test_from_int()

    def test_from_signature(self):
        profile = FeatureProfile.from_signature(self.signature)
        self._test_profile(profile)

    def _test_kwargs(self, prefix):
        profile = FeatureProfile.from_int(self.features)
        kwargs = profile.to_kwargs(prefix=prefix)

        ok_(all([k.startswith(prefix) for k in kwargs.keys()]))
        eq_(kwargs.values().count(False), bin(self.features)[2:].count('0'))
        eq_(len(kwargs.values()), len(APP_FEATURES) - len(self.truths))

    def test_to_kwargs(self):
        self._test_kwargs('')
        self._test_kwargs('prefix_')
