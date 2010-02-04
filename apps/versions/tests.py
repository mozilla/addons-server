from django import test

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
