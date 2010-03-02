from django import test

from nose.tools import eq_

import amo
from versions.models import License, Version


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

    def test_has_files(self):
        v = Version.objects.get(pk=24007)
        assert v.has_files, 'Version with files not recognized.'

        v = Version.objects.get(pk=2)
        assert not v.has_files, 'Version without files not recognized.'


class TestLicense(test.TestCase):
    """Test built-in as well as custom licenses."""

    def test_defaults(self):
        lic = License()
        lic.save()
        assert lic.is_custom, 'Custom license not recognized.'
        assert lic.license_type is amo.LICENSE_CUSTOM # default
        assert not lic.text

        lic.license_type = amo.LICENSE_MPL
        assert not lic.is_custom, 'Built-in license not recognized.'
        assert lic.text
        eq_(lic.url, amo.LICENSE_MPL.url)

    def test_license(self):
        """Test getters and setters for license."""
        mylicense = amo.LICENSE_MPL

        lic = License()
        lic.license_type = mylicense
        lic.save()
        eq_(lic.license_type, mylicense)

    def test_custom_text(self):
        """Test getters and setters for custom text."""
        mytext = 'OMG'

        lic = License()
        lic.text = mytext
        lic.save()
        lic2 = License.objects.get(pk=lic.pk)
        eq_(unicode(lic2.text), mytext)

    def test_builtin_text(self):
        """Get license text for all built-in licenses."""
        lic = License()
        for licensetype in amo.LICENSES:
            lic.license_type = licensetype
            if licensetype == amo.LICENSE_CUSTOM:
                assert not lic.text
            else:
                assert lic.text
