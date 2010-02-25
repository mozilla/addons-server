from django import test

from nose.tools import eq_

import amo
from versions.models import Version


class TestVersion(test.TestCase):
    """
    Test methods of the version class.
    """

    fixtures = ['base/addons.json']

    def test_compatible_apps(self):
        v = Version.objects.get(pk=2)

        assert amo.FIREFOX in v.compatible_apps, "Missing Firefox >_<"
        assert amo.THUNDERBIRD in v.compatible_apps, "Missing Thunderbird \o/"

    def test_supported_platforms(self):
        v = Version.objects.get(pk=24007)
        assert 'ALL' in [str(os) for os in v.supported_platforms]

    def test_major_minor(self):
        """Check that major/minor/alpha is getting set."""
        v = Version(version='3.0.12b2')
        eq_(v.major, 3)
        eq_(v.minor1, 0)
        eq_(v.minor2, 12)
        eq_(v.minor3, None)
        eq_(v.alpha, 'b')
        eq_(v.alpha_ver, 2)

        v = Version(version='3.6.1apre2+')
        eq_(v.major, 3)
        eq_(v.minor1, 6)
        eq_(v.minor2, 1)
        eq_(v.alpha, 'a')
        eq_(v.pre, 'pre')
        eq_(v.pre_ver, 2)

        v = Version(version='')
        eq_(v.major, None)
        eq_(v.minor1, None)
        eq_(v.minor2, None)
        eq_(v.minor3, None)
