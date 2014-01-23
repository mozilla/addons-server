from mock import patch
from nose.tools import eq_, ok_

import amo.tests
from mkt.api.urls import include_version


# Semantic names for the relevant values in the tuple returned by include().
MODULE, NAMESPACE = 0, 2


class TestIncludeVersion(amo.tests.TestCase):
    def includes(self):
        return include_version(1), include_version(2)

    @patch('django.conf.settings.API_CURRENT_VERSION', 1)
    def test_v1(self):
        v1, v2 = self.includes()

        eq_(v1[NAMESPACE], None)
        eq_(v2[NAMESPACE], 'api-v2')

        ok_('v1' in v1[MODULE].__file__)
        ok_('v2' in v2[MODULE].__file__)

    @patch('django.conf.settings.API_CURRENT_VERSION', 2)
    def test_v2(self):
        v1, v2 = self.includes()

        eq_(v1[NAMESPACE], 'api-v1')
        eq_(v2[NAMESPACE], None)

        ok_('v1' in v1[MODULE].__file__)
        ok_('v2' in v2[MODULE].__file__)
