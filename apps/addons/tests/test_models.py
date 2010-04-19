from datetime import date

from django import test
from django.conf import settings
from django.core.cache import cache

from nose.tools import eq_, assert_not_equal
import test_utils

import amo
from addons.models import Addon, AddonPledge, AddonType, Category, Persona
from reviews.models import Review
from users.models import UserProfile
from versions.models import Version


class TestAddonManager(test_utils.TestCase):
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

        # If we search for public or unreviewed we find it.
        addon.inactive = False
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        eq_(q.count(), 0)
        eq_(Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC,
                                 amo.STATUS_UNREVIEWED).count(), 1)

        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        eq_(q.count(), 0)

    def test_public(self):
        public = Addon.objects.public()
        for a in public:
            assert_not_equal(
                a.id, 3, 'public() must not return unreviewed add-ons')

    def test_unreviewed(self):
        """
        Tests for unreviewed addons.
        """
        exp = Addon.objects.unreviewed()

        for addon in exp:
            assert addon.status in amo.UNREVIEWED_STATUSES, (
                    "unreviewed() must return unreviewed addons.")


class TestAddonModels(test_utils.TestCase):
    # base/addons.json has an example addon
    fixtures = ['base/addons.json', 'addons/featured.json',
                'addons/invalid_latest_version.json']

    def test_current_version(self):
        """
        Tests that we get the current (latest public) version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        eq_(a.current_version.id, 24007)

    def test_current_version_listed(self):
        a = Addon.objects.get(pk=3723)
        eq_(a.current_version.id, 89774)

    def test_current_version_listed_no_version(self):
        Version.objects.filter(addon=3723).delete()
        a = Addon.objects.get(pk=3723)
        eq_(a.current_version, None)

    def test_current_beta_version(self):
        a = Addon.objects.get(pk=5299)
        eq_(a.current_beta_version.id, 78841)

    def test_current_version_unreviewed(self):
        a = Addon.objects.get(pk=55)
        eq_(a.current_version.id, 55)

    def test_current_version_mixed_statuses(self):
        """Mixed file statuses are evil (bug 558237)."""
        a = Addon.objects.get(pk=3895)
        # Last version has pending files, so second to last version is
        # considered "current".
        eq_(a.current_version.id, 78829)

        # Fix file statuses on last version.
        v = Version.objects.get(pk=98217)
        v.files.update(status=amo.STATUS_PUBLIC)

        # Wipe caches.
        cache.clear()
        del a.__dict__['current_version']

        # Make sure the updated version is now considered current.
        eq_(a.current_version.id, v.id)

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
        assert a.icon_url.endswith('/icons/default-theme.png'), (
                "No match for %s" % a.icon_url)
        a = Addon.objects.get(pk=73)
        assert a.icon_url.endswith('/icons/default-addon.png')

    def test_thumbnail_url(self):
        """
        Test for the actual thumbnail URL if it should exist, or the no-preview
        url.
        """
        a = Addon.objects.get(pk=7172)
        a.thumbnail_url.index('/previews/thumbs/25/25981.png?modified=')
        a = Addon.objects.get(pk=73)
        assert a.thumbnail_url.endswith('/icons/no-preview.png'), (
                "No match for %s" % a.thumbnail_url)

    def test_is_unreviewed(self):
        """Test if add-on is unreviewed or not"""
        # public add-on
        a = Addon.objects.get(pk=3615)
        assert not a.is_unreviewed(), 'public add-on: is_unreviewed=False'

        # unreviewed add-on
        a = Addon(status=amo.STATUS_UNREVIEWED)
        assert a.is_unreviewed(), 'sandboxed add-on: is_unreviewed=True'

    def test_is_selfhosted(self):
        """Test if an add-on is listed or hosted"""
        # hosted
        a = Addon.objects.get(pk=3615)
        assert not a.is_selfhosted(), 'hosted add-on => !is_selfhosted()'

        # listed
        a.status = amo.STATUS_LISTED
        assert a.is_selfhosted(), 'listed add-on => is_selfhosted()'

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

    def test_has_eula(self):
        addon = lambda: Addon.objects.get(pk=3615)
        assert not addon().has_eula

        a = addon()
        a.eula = ''
        a.save()
        assert not addon().has_eula

        a.eula = 'eula'
        a.save()
        assert addon().has_eula

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=2519)
        version = addon.current_version
        new_review = Review(version=version, user=u, rating=2, body='hello')
        new_review.save()
        new_reply = Review(version=version, user=addon.authors.all()[0],
                           reply_to=new_review, rating=2, body='my reply')
        new_reply.save()

        review_list = [r.pk for r in addon.reviews]

        assert new_review.pk in review_list, (
            'Original review must show up in review list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.')


class TestCategoryModel(test_utils.TestCase):

    def test_category_url(self):
        """Every type must have a url path for its categories."""
        for t in amo.ADDON_TYPE.keys():
            cat = Category(type=AddonType(id=t), slug='omg')
            assert cat.get_url_path()


class TestAddonPledgeModel(test_utils.TestCase):
    fixtures = ['stats/test_models.json']

    def test_ongoing(self):
        """Make sure ongoing pledges are returned correctly."""
        myaddon = Addon.objects.get(id=4)
        mypledge = AddonPledge(addon=myaddon, target=10,
                               created=date(2009, 6, 1),
                               deadline=date(2009, 7, 1))
        mypledge.save()

        mypledge2 = AddonPledge(addon=myaddon, target=10,
                                created=date(2009, 6, 1),
                                deadline=date.today())
        mypledge2.save()

        ongoing = AddonPledge.objects.ongoing()
        eq_(ongoing.count(), 1)
        eq_(ongoing[0], mypledge2)

    def test_contributions(self):
        myaddon = Addon.objects.get(id=4)
        mypledge = AddonPledge(addon=myaddon, target=10,
                               created=date(2009, 6, 1),
                               deadline=date(2009, 7, 1))

        # Only the two valid contributions must be counted.
        eq_(mypledge.num_users, 2)
        self.assertAlmostEqual(mypledge.raised, 4.98)

    def test_raised(self):
        """AddonPledge.raised should never return None."""
        pledge = AddonPledge.objects.create(addon_id=4, target=230,
                                            deadline=date.today())
        eq_(pledge.raised, 0)


class TestPersonaModel(test_utils.TestCase):

    def test_image_urls(self):
        mypersona = Persona(id=1234, persona_id=9876)
        assert mypersona.thumb_url.endswith('/7/6/9876/preview.jpg')
        assert mypersona.preview_url.endswith('/7/6/9876/preview_large.jpg')
