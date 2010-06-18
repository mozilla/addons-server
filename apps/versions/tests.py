from nose.tools import eq_
import test_utils

import amo
from amo.urlresolvers import reverse
from addons.models import Addon
from versions import views
from versions.models import License, Version
from versions.compare import version_int, dict_from_int


def test_version_int():
    """Tests that version_int. Corrects our versions."""
    eq_(version_int("3.5.0a1pre2"), 3050000001002)
    eq_(version_int(""), 200100)


def test_dict_from_int():
    d = dict_from_int(3050000001002)
    eq_(d['major'], 3)
    eq_(d['minor1'], 5)
    eq_(d['minor2'], 0)
    eq_(d['minor3'], 0)
    eq_(d['alpha'], 'a')
    eq_(d['alpha_ver'], 1)
    eq_(d['pre'], 'pre')
    eq_(d['pre_ver'], 2)


class TestVersion(test_utils.TestCase):
    """
    Test methods of the version class.
    """

    fixtures = ['base/fixtures']

    def test_compatible_apps(self):
        v = Version.objects.get(pk=2)

        assert amo.FIREFOX in v.compatible_apps, "Missing Firefox >_<"
        assert amo.THUNDERBIRD in v.compatible_apps, "Missing Thunderbird \o/"

    def test_supported_platforms(self):
        v = Version.objects.get(pk=24007)
        assert amo.PLATFORM_ALL in v.supported_platforms

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


class TestLicense(test_utils.TestCase):
    """Test built-in as well as custom licenses."""

    def test_defaults(self):
        lic = License()
        lic.save()
        assert lic.is_custom, 'Custom license not recognized.'
        assert lic.license_type is amo.LICENSE_CUSTOM  # default
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
            if not licensetype.shortname:
                assert not lic.text
            else:
                assert lic.text


class TestViews(test_utils.TestCase):
    fixtures = ['addons/eula+contrib-addon']

    def setUp(self):
        self.old_perpage = views.PER_PAGE
        views.PER_PAGE = 1

    def tearDown(self):
        views.PER_PAGE = self.old_perpage

    def test_version_detail(self):
        base = '/en-US/firefox/addon/11730/versions/'
        a = Addon.objects.get(id=11730)
        urls = [(v.id, reverse('addons.versions', args=[a.id, v.id]))
                for v in a.versions.all()]

        version, url = urls[0]
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, base + '?page=1#version-%s' % version)

        version, url = urls[1]
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, base + '?page=2#version-%s' % version)

    def test_version_detail_404(self):
        r = self.client.get(reverse('addons.versions', args=[11730, 2]))
        eq_(r.status_code, 404)
