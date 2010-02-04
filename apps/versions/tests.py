from django import test

import amo
from versions.models import Version


class TestVersion(test.TestCase):
    """
    Test methods of the version class.
    """

    fixtures = ['base/addons.json']

    def test_get_compatible_apps(self):
        v = Version.objects.get(pk=2)

        assert any([c.application.id == amo.FIREFOX.id for c in
                   v.get_compatible_apps()]), "Missing Firefox >_<"
        assert any([c.application.id == amo.THUNDERBIRD.id for c in
                   v.get_compatible_apps()]), "Missing Thunderbird \o/"

    def test_get_supported_platforms(self):
        v = Version.objects.get(pk=24007)
        assert any(os.localized_string == 'ALL' for os in
                   v.get_supported_platforms())
