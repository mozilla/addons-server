from datetime import date
import itertools
from urlparse import urlparse

from django.conf import settings
from django.core.cache import cache

from mock import patch
from nose.tools import eq_, assert_not_equal
import test_utils

import amo
from amo.signals import _connect, _disconnect
from addons.models import (Addon, AddonDependency, AddonPledge,
                           AddonRecommendation, AddonType, Category, Feature,
                           Persona, Preview)
from files.models import File
from applications.models import Application, AppVersion
from reviews.models import Review
from users.models import UserProfile
from versions.models import ApplicationsVersions, Version


class TestAddonManager(test_utils.TestCase):
    fixtures = ['base/addon_5299_gcal', 'addons/test_manager']

    def test_featured(self):
        featured = Addon.objects.featured(amo.FIREFOX)[0]
        eq_(featured.id, 1)
        eq_(Addon.objects.featured(amo.FIREFOX).count(), 1)

    def test_listed(self):
        Addon.objects.filter(id=5299).update(disabled_by_user=True)
        # Should find one addon.
        q = Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC)
        eq_(len(q.all()), 1)

        addon = q[0]
        eq_(addon.id, 1)

        # Disabling hides it.
        addon.disabled_by_user = True
        addon.save()
        eq_(q.count(), 0)

        # If we search for public or unreviewed we find it.
        addon.disabled_by_user = False
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
    fixtures = ['base/apps',
                'base/users',
                'base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple.json',
                'base/addon_4594_a9',
                'base/addon_4664_twitterbar',
                'addons/featured',
                'addons/invalid_latest_version']

    def test_current_version(self):
        """
        Tests that we get the current (latest public) version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        eq_(a.current_version.id, 81551)

    def test_current_version_listed(self):
        a = Addon.objects.get(pk=3723)
        eq_(a.current_version.id, 89774)

    def test_current_version_listed_no_version(self):
        Addon.objects.filter(pk=3723).update(_current_version=None)
        Version.objects.filter(addon=3723).delete()
        a = Addon.objects.get(pk=3723)
        eq_(a.current_version, None)

    def test_current_beta_version(self):
        a = Addon.objects.get(pk=5299)
        eq_(a.current_beta_version.id, 50000)

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
        a.update_current_version()

        # Make sure the updated version is now considered current.
        eq_(a.current_version.id, v.id)

    def test_incompatible_latest_apps(self):
        a = Addon.objects.get(pk=3615)
        eq_(a.incompatible_latest_apps(), [])

        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.get(pk=97)  # Firefox 2.0
        av.save()

        a = Addon.objects.get(pk=3615)
        eq_(a.incompatible_latest_apps(), [amo.FIREFOX])

        # Check a search engine addon.
        a = Addon.objects.get(pk=4594)
        eq_(a.incompatible_latest_apps(), [])

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
        a = Addon.objects.get(pk=6704)
        a.icon_type = None
        assert a.icon_url.endswith('/icons/default-theme.png'), (
                "No match for %s" % a.icon_url)
        a = Addon.objects.get(pk=3615)
        a.icon_type = None
        assert a.icon_url.endswith('/icons/default-addon.png')

    def test_thumbnail_url(self):
        """
        Test for the actual thumbnail URL if it should exist, or the no-preview
        url.
        """
        a = Addon.objects.get(pk=4664)
        a.thumbnail_url.index('/previews/thumbs/20/20397.png?modified=')
        a = Addon.objects.get(pk=5299)
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

        a.status = amo.STATUS_PENDING
        assert a.is_unreviewed(), 'pending add-on: is_unreviewed=True'

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
        Feature.objects.filter(addon=1001).delete()
        a = Addon.objects.get(pk=1001)
        assert not a.is_featured(amo.FIREFOX, 'en-US')

        assert a.is_category_featured(amo.FIREFOX, 'en-US')

    def test_has_full_profile(self):
        """Test if an add-on's developer profile is complete (public)."""
        addon = lambda: Addon.objects.get(pk=3615)
        assert not addon().has_full_profile()

        a = addon()
        a.the_reason = 'some reason'
        a.save()
        assert not addon().has_full_profile()

        a.the_future = 'some future'
        a.save()
        assert addon().has_full_profile()

        a.the_reason = ''
        a.the_future = ''
        a.save()
        assert not addon().has_full_profile()

    def test_has_profile(self):
        """Test if an add-on's developer profile is (partially or entirely)
        completed.

        """
        addon = lambda: Addon.objects.get(pk=3615)
        assert not addon().has_profile()

        a = addon()
        a.the_reason = 'some reason'
        a.save()
        assert addon().has_profile()

        a.the_future = 'some future'
        a.save()
        assert addon().has_profile()

        a.the_reason = ''
        a.the_future = ''
        a.save()
        assert not addon().has_profile()

    def test_has_eula(self):
        addon = lambda: Addon.objects.get(pk=3615)
        assert addon().has_eula

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
        u = UserProfile.objects.get(pk=999)
        version = addon.current_version
        new_review = Review(version=version, user=u, rating=2, body='hello',
                            addon=addon)
        new_review.save()
        new_reply = Review(version=version, user=addon.authors.all()[0],
                           addon=addon, reply_to=new_review,
                           rating=2, body='my reply')
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
            if t == amo.ADDON_DICT:
                continue  # Language packs don't have categories.
            cat = Category(type=AddonType(id=t), slug='omg')
            assert cat.get_url_path()


class TestAddonPledgeModel(test_utils.TestCase):
    fixtures = ['stats/test_models']

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

    def test_update_url(self):
        p = Persona(id=1234, persona_id=9876)
        assert p.update_url.endswith('9876')


class TestPreviewModel(test_utils.TestCase):

    fixtures = ['base/previews']

    def test_as_dict(self):
        expect = ['caption', 'full', 'thumbnail']
        reality = sorted(Preview.objects.all()[0].as_dict().keys())
        eq_(expect, reality)


class TestAddonRecommendations(test_utils.TestCase):
    fixtures = ['base/addon-recs']

    def test_scores(self):
        ids = [5299, 1843, 2464, 7661, 5369]
        scores = AddonRecommendation.scores(ids)
        q = AddonRecommendation.objects.filter(addon__in=ids)
        for addon, recs in itertools.groupby(q, lambda x: x.addon_id):
            for rec in recs:
                eq_(scores[addon][rec.other_addon_id], rec.score)


class TestAddonDependencies(test_utils.TestCase):
    fixtures = ['base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple',
                'base/addon_4664_twitterbar']

    def test_dependencies(self):
        ids = [3615, 3723, 4664, 6704]
        a = Addon.objects.get(id=5299)

        for dependent_id in ids:
            AddonDependency(addon=a,
                dependent_addon=Addon.objects.get(id=dependent_id)).save()

        eq_(sorted([a.id for a in a.dependencies.all()]), sorted(ids))


class TestListedAddonTwoVersions(test_utils.TestCase):
    fixtures = ['addons/listed-two-versions']

    def test_listed_two_versions(self):
        Addon.objects.get(id=2795)  # bug 563967


class TestFlushURLs(test_utils.TestCase):
    fixtures = ['base/addon_5579',
                'base/previews',
                'base/addon_4664_twitterbar',
                'addons/persona']

    def setUp(self):
        settings.ADDON_ICON_URL = (
            '%s/%s/%s/images/addon_icon/%%d/?modified=%%s' % (
            settings.STATIC_URL, settings.LANGUAGE_CODE, settings.DEFAULT_APP))
        settings.PREVIEW_THUMBNAIL_URL = (settings.STATIC_URL +
            '/img/uploads/previews/thumbs/%s/%d.png?modified=%d')
        settings.PREVIEW_FULL_URL = (settings.STATIC_URL +
            '/img/uploads/previews/full/%s/%d.png?modified=%d')
        _connect()

    def tearDown(self):
        _disconnect()

    def is_url_hashed(self, url):
        return urlparse(url).query.find('modified') > -1

    @patch('amo.tasks.flush_front_end_cache_urls.apply_async')
    def test_addon_flush(self, flush):
        addon = Addon.objects.get(pk=159)
        addon.icon_type = "image/png"
        addon.save()

        for url in (addon.thumbnail_url, addon.icon_url):
            assert url in flush.call_args[1]['args'][0]
            assert self.is_url_hashed(url), url

    @patch('amo.tasks.flush_front_end_cache_urls.apply_async')
    def test_preview_flush(self, flush):
        addon = Addon.objects.get(pk=4664)
        preview = addon.previews.all()[0]
        preview.save()
        for url in (preview.thumbnail_url, preview.image_url):
            assert url in flush.call_args[1]['args'][0]
            assert self.is_url_hashed(url), url


class TestUpdate(test_utils.TestCase):
    fixtures = ['addons/update',
                'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.get(id=1865)
        self.get = self.addon.get_current_version_for_client
        self.platform = None
        self.version_int = 3069900200100
        self.app = Application.objects.get(id=1)

    def test_low_client(self):
        """Test a low client number. 86 is version 3.0a1 of Firefox,
        which means we have version int of 3000000001100
        and hence version 1.0.2 of the addon."""
        version, file = self.get('', '3000000001100',
                                 self.app, self.platform)
        eq_(version.version, '1.0.2')

    def test_new_client(self):
        """Test a high client number. 291 is version 3.0.12 of Firefox,
        which means we have a version int of 3069900200100
        and hence version 1.2.2 of the addon."""
        version, file = self.get('', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.2')

    def test_new_client_ordering(self):
        """Given the following:
        * Version 15 (1 day old), max application_version 3.6*
        * Version 12 (1 month old), max application_version 3.7a
        We want version 15, even though version 12 is for a higher version.
        This was found in https://bugzilla.mozilla.org/show_bug.cgi?id=615641.
        """
        application_version = ApplicationsVersions.objects.get(pk=77550)
        application_version.max_id = 350
        application_version.save()

        # Version 1.2.2 is now a lower max version.
        application_version = ApplicationsVersions.objects.get(pk=88490)
        application_version.max_id = 329
        application_version.save()

        version, file = self.get('', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.2')

    def test_public_not_beta(self):
        """If the addon status is public and you are not asking
        for a beta version, then you get a public version."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.status = amo.STATUS_PENDING
            file.save()
        # We've made 1.2.2 pending so that it will not be selected
        # and the highest version is 1.2.1

        eq_(self.addon.status, amo.STATUS_PUBLIC)
        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.1')

    def test_public_beta(self):
        """If the addon status is public and you are asking
        for a beta version and there are no beta upgrades, then
        you won't get an update."""
        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        assert not version

    def test_public_pending_not_exists(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking for another version
        with a file pending. This ends up being itself."""
        version = Version.objects.get(pk=105387)
        version.version = '1.2beta'
        version.save()

        # set the current version to pending
        file = version.files.all()[0]
        file.status = amo.STATUS_PENDING
        file.save()

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2beta')

    def test_public_pending_no_file_no_beta(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. If there are no files,
        we look for a beta. That does not exist."""
        version = Version.objects.get(pk=105387)
        version.version = '1.2beta'
        version.save()

        version.files.all().delete()

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        assert not version

    def test_public_pending_no_file_has_beta(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. If there are no files,
        we look for a beta. That does exist."""
        version = Version.objects.get(pk=105387)
        version.version = '1.2beta'
        version.save()

        version.files.all().delete()

        version = Version.objects.get(pk=112396)
        file = version.files.all()[0]
        file.status = amo.STATUS_BETA
        file.save()

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.1')

    def test_public_pending_exists(self):
        """If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking for another version
        with a file pending. That does exist."""
        version = Version.objects.get(pk=105387)
        version.version = '1.2beta'
        version.save()

        # set the current version to pending
        file = version.files.all()[0]
        file.status = amo.STATUS_PENDING
        file.save()

        version = Version.objects.get(pk=112396)
        file = version.files.all()[0]
        file.status = amo.STATUS_PENDING
        file.save()

        version, file = self.get('1.2beta', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.1')

    def test_not_public(self):
        """If the addon status is not public, then the update only
        looks for files within that one version."""
        addon = self.addon
        addon.status = amo.STATUS_PENDING
        addon.save()

        version, file = self.get('1.2.1', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.1')

    def test_platform_does_not_exist(self):
        """If client passes a platform, find that specific platform."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.platform_id = amo.PLATFORM_LINUX.id
            file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, self.platform)
        eq_(version.version, '1.2.1')

    def test_platform_exists(self):
        """If client passes a platform, find that specific platform."""
        version = Version.objects.get(pk=115509)
        for file in version.files.all():
            file.platform_id = amo.PLATFORM_LINUX.id
            file.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version.version, '1.2.2')

    def test_file_for_platform(self):
        """If client passes a platform, make sure we get the right file."""
        version = Version.objects.get(pk=115509)
        file_one = version.files.all()[0]
        file_one.platform_id = amo.PLATFORM_LINUX.id
        file_one.save()

        file_two = File(version=version, filename='foo', hash='bar',
                        platform_id=amo.PLATFORM_WIN.id,
                        status=amo.STATUS_PUBLIC)
        file_two.save()

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_LINUX)
        eq_(version.version, '1.2.2')
        eq_(file.pk, file_one.pk)

        version, file = self.get('1.2', self.version_int,
                                 self.app, amo.PLATFORM_WIN)
        eq_(version.version, '1.2.2')
        eq_(file.pk, file_two.pk)
