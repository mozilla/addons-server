from django import test
from django.conf import settings

from nose.tools import eq_, assert_not_equal
import test_utils

import amo
from addons.models import Addon


class TestAddonManager(test_utils.TestCase):
    fixtures = ['addons/test_manager']

    def test_compatible_with_app(self):
        eq_(len(Addon.objects.compatible_with_app(amo.FIREFOX, '4.0')), 0)

    def test_compatible_with_platform(self):
        mac_friendly = Addon.objects.compatible_with_platform('macosx')
        for addon in mac_friendly:
            platform_ids = [file.platform_id for file in
                    addon.current_version.files.all()]
            assert (amo.PLATFORM_MAC in platform_ids or
                    amo.PLATFORM_ALL in platform_ids)

    def test_compatible_with_platform_fake(self):
        "Given a fake platform, we should still get results."

        fake_platform = Addon.objects.compatible_with_platform('fake')
        assert len(fake_platform)

    def test_featured(self):
        featured = Addon.objects.featured(amo.FIREFOX)[0]
        eq_(featured.id, 1)
        eq_(Addon.objects.featured(amo.FIREFOX).count(), 1)

        # Mess with the Feature's start and end date.
        feature = featured.feature_set.all()[0]
        prev_end = feature.end
        feature.end = feature.start
        feature.save()
        eq_(Addon.objects.featured(amo.FIREFOX).count(), 0)
        feature.end = prev_end

        feature.start = feature.end
        eq_(Addon.objects.featured(amo.FIREFOX).count(), 0)

        featured = Addon.objects.featured(amo.THUNDERBIRD)[0]
        eq_(featured.id, 2)
        eq_(Addon.objects.featured(amo.THUNDERBIRD).count(), 1)

    def test_listed(self):
        # Should find one addon.
        q = Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC)
        eq_(len(q.all()), 1)

        addon = q[0]
        eq_(addon.id, 1)

        # Making it inactive hides it.
        addon.inactive = True
        addon.save()
        eq_(q.count(), 0)

        # If we search for public or experimental we find it.
        addon.inactive = False
        addon.status = amo.STATUS_SANDBOX
        addon.save()
        eq_(q.count(), 0)
        eq_(Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC,
                                 amo.STATUS_SANDBOX).count(), 1)


        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        eq_(q.count(), 0)

    def test_public(self):
        public = Addon.objects.public()
        for a in public:
            assert_not_equal(
                a.id, 3, 'public() must not return experimental add-ons')

    def test_experimental(self):
        """
        Tests for experimental addons.
        """
        exp = Addon.objects.experimental()

        for addon in exp:
            assert addon.status in amo.EXPERIMENTAL_STATUSES, (
                    "experimental() must return experimental addons.")


class TestAddonModels(test.TestCase):
    # base/addons.json has an example addon
    fixtures = ['base/addons.json', 'addons/featured.json']

    def test_current_version(self):
        """
        Tests that we get the current (latest public) version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        eq_(a.current_version.id, 24007)

    def test_current_beta_version(self):
        a = Addon.objects.get(pk=5299)
        eq_(a.current_beta_version.id, 78841)

    def test_current_version_experimental(self):
        a = Addon.objects.get(pk=55)
        eq_(a.current_version.id, 55)

    def test_icon_url(self):
        """
        Tests for various icons.
        1. Test for an icon that exists.
        2. Test for default THEME icon.
        3. Test for default non-THEME icon.
        """
        a = Addon.objects.get(pk=3615)
        expected = (settings.ADDON_ICON_URL % (3615, 0)).rstrip('/0')
        assert a.icon_url.startswith(expected)
        a = Addon.objects.get(pk=7172)
        assert a.icon_url.endswith('/img/theme.png'), (
                "No match for %s" % a.icon_url)
        a = Addon.objects.get(pk=73)
        assert a.icon_url.endswith('/img/default_icon.png')

    def test_thumbnail_url(self):
        """
        Test for the actual thumbnail URL if it should exist, or the no-preview
        url.
        """
        a = Addon.objects.get(pk=7172)
        a.thumbnail_url.index('/previews/thumbs/25/25981.png?modified=')
        a = Addon.objects.get(pk=73)
        assert a.thumbnail_url.endswith('/img/no-preview.png'), (
                "No match for %s" % a.thumbnail_url)

    def test_preview_count(self):
        """Test if preview count is accurate"""
        a = Addon.objects.get(pk=7172)
        eq_(a.preview_count, 1)

        a = Addon.objects.get(pk=73)
        eq_(a.preview_count, 0)

    def test_is_experimental(self):
        """Test if add-on is experimental or not"""
        # public add-on
        a = Addon.objects.get(pk=3615)
        assert not a.is_experimental(), 'public add-on: is_experimental=False'

        # experimental add-on
        a = Addon(status=amo.STATUS_SANDBOX)
        assert a.is_experimental(), 'sandboxed add-on: is_experimental=True'

    def test_is_listed(self):
        """Test if an add-on is listed or hosted"""
        # hosted
        a = Addon.objects.get(pk=3615)
        assert not a.is_listed, 'hosted add-on => !is_listed()'

        # listed
        a.status = amo.STATUS_LISTED
        assert a.is_listed, 'listed add-on => is_listed()'


    def test_is_featured(self):
        """Test if an add-on is globally featured"""
        a = Addon.objects.get(pk=1003)
        assert a.is_featured(amo.FIREFOX, 'en-US'), (
            'globally featured add-on not recognized')

    def test_is_category_featured(self):
        """Test if an add-on is category featured"""
        a = Addon.objects.get(pk=1001)
        assert not a.is_featured(amo.FIREFOX, 'en-US'), (
            'category featured add-on mistaken for globally featured')

        assert a.is_category_featured(amo.FIREFOX, 'en-US'), (
            'category featured add-on not recognized')
