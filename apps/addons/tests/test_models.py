from django import test
from django.conf import settings

from nose.tools import eq_

import amo
from addons.models import Addon, Feature


class TestAddonManager(test.TestCase):
    fixtures = ['addons/test_manager']

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


class TestAddonModels(test.TestCase):
    # base/addons.json has an example addon
    fixtures = ['base/addons.json', 'addons/featured.json']

    def test_current_version(self):
        """
        Tests that we get the current (latest public) version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        eq_(a.current_version.id, 24007)

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
        a = Addon.objects.get(pk=1)
        assert a.icon_url.endswith('/img/default_icon.png')

    def test_thumbnail_url(self):
        """
        Test for the actual thumbnail URL if it should exist, or the no-preview
        url.
        """
        a = Addon.objects.get(pk=7172)
        a.thumbnail_url.index('/previews/thumbs/25/25981.png?modified=')
        a = Addon.objects.get(pk=1)
        assert a.thumbnail_url.endswith('/img/no-preview.png'), (
                "No match for %s" % a.thumbnail_url)

    def test_is_experimental(self):
        """Test if add-on is experimental or not"""
        # public add-on
        a = Addon.objects.get(pk=3615)
        assert not a.is_experimental(), 'public add-on: is_experimental=False'

        # experimental add-on
        a = Addon(status=amo.STATUS_SANDBOX)
        assert a.is_experimental(), 'sandboxed add-on: is_experimental=True'

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
