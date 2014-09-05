# -*- coding: utf-8 -*-
import itertools
import os
import time
from datetime import datetime, timedelta
from urlparse import urlparse

from django import forms
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import translation

from mock import Mock, patch
from nose.tools import assert_not_equal, eq_, ok_

import amo
import amo.tests
from amo import set_user
from amo.helpers import absolutify, user_media_url
from amo.signals import _connect, _disconnect
from addons.models import (Addon, AddonCategory, AddonDependency,
                           AddonDeviceType, AddonRecommendation,
                           AddonUser, AppSupport, BlacklistedGuid,
                           BlacklistedSlug, Category, Charity, CompatOverride,
                           CompatOverrideRange, FrozenAddon,
                           IncompatibleVersions, Persona, Preview)
from applications.models import Application, AppVersion
from constants.applications import DEVICE_TYPES
from devhub.models import ActivityLog, AddonLog, RssKey, SubmitStep
from editors.models import EscalationQueue
from files.models import File, Platform
from files.tests.test_models import UploadTest
from reviews.models import Review, ReviewFlag
from translations.models import Translation, TranslationSequence
from users.models import UserProfile
from versions.models import ApplicationsVersions, Version
from versions.compare import version_int


class TestCleanSlug(amo.tests.TestCase):

    def test_clean_slug_new_object(self):
        # Make sure there's at least an addon with the "addon" slug, subsequent
        # ones should be "addon-1", "addon-2" ...
        a = Addon.objects.create()
        eq_(a.slug, "addon")

        # Start with a first clash. This should give us "addon-1".
        # We're not saving yet, we're testing the slug creation without an id.
        b = Addon()
        b.clean_slug()
        eq_(b.slug, 'addon-1')
        # Now save the instance to the database for future clashes.
        b.save()

        # Test on another object without an id.
        c = Addon()
        c.clean_slug()
        eq_(c.slug, 'addon-2')

        # Even if an addon is deleted, don't clash with its slug.
        c.status = amo.STATUS_DELETED
        # Now save the instance to the database for future clashes.
        c.save()

        # And yet another object without an id. Make sure we're not trying to
        # assign the 'addon-2' slug from the deleted addon.
        d = Addon()
        d.clean_slug()
        eq_(d.slug, 'addon-3')

    def test_clean_slug_with_id(self):
        # Create an addon and save it to have an id.
        a = Addon.objects.create()
        # Start over: don't use the name nor the id to generate the slug.
        a.slug = a.name = ""
        a.clean_slug()
        # Slugs created from an id are of the form "id~", eg "123~" to avoid
        # clashing with URLs.
        eq_(a.slug, "%s~" % a.id)

        # And again, this time make it clash.
        b = Addon.objects.create()
        # Set a's slug to be what should be created for b from its id.
        a.slug = "%s~" % b.id
        a.save()

        # Now start over for b.
        b.slug = b.name = ""
        b.clean_slug()
        eq_(b.slug, "%s~-1" % b.id)

    def test_clean_slug_with_name(self):
        # Make sure there's at least an addon with the "fooname" slug,
        # subsequent ones should be "fooname-1", "fooname-2" ...
        a = Addon.objects.create(name="fooname")
        eq_(a.slug, "fooname")

        b = Addon(name="fooname")
        b.clean_slug()
        eq_(b.slug, "fooname-1")

    def test_clean_slug_with_slug(self):
        # Make sure there's at least an addon with the "fooslug" slug,
        # subsequent ones should be "fooslug-1", "fooslug-2" ...
        a = Addon.objects.create(name="fooslug")
        eq_(a.slug, "fooslug")

        b = Addon(name="fooslug")
        b.clean_slug()
        eq_(b.slug, "fooslug-1")

    def test_clean_slug_blacklisted_slug(self):
        blacklisted_slug = 'fooblacklisted'
        BlacklistedSlug.objects.create(name=blacklisted_slug)

        a = Addon(slug=blacklisted_slug)
        a.clean_slug()
        # Blacklisted slugs (like "activate" or IDs) have a "~" appended to
        # avoid clashing with URLs.
        eq_(a.slug, "%s~" % blacklisted_slug)
        # Now save the instance to the database for future clashes.
        a.save()

        b = Addon(slug=blacklisted_slug)
        b.clean_slug()
        eq_(b.slug, "%s~-1" % blacklisted_slug)

    def test_clean_slug_blacklisted_slug_long_slug(self):
        long_slug = "this_is_a_very_long_slug_that_is_longer_than_thirty_chars"
        BlacklistedSlug.objects.create(name=long_slug[:30])

        # If there's no clashing slug, just append a "~".
        a = Addon.objects.create(slug=long_slug[:30])
        eq_(a.slug, "%s~" % long_slug[:29])

        # If there's a clash, use the standard clash resolution.
        a = Addon.objects.create(slug=long_slug[:30])
        eq_(a.slug, "%s-1" % long_slug[:27])

    def test_clean_slug_long_slug(self):
        long_slug = "this_is_a_very_long_slug_that_is_longer_than_thirty_chars"

        # If there's no clashing slug, don't over-shorten it.
        a = Addon.objects.create(slug=long_slug)
        eq_(a.slug, long_slug[:30])

        # Now that there is a clash, test the clash resolution.
        b = Addon(slug=long_slug)
        b.clean_slug()
        eq_(b.slug, "%s-1" % long_slug[:27])

    def test_clean_slug_always_slugify(self):
        illegal_chars = "some spaces and !?@"

        # Slugify if there's a slug provided.
        a = Addon(slug=illegal_chars)
        a.clean_slug()
        assert a.slug.startswith("some-spaces-and"), a.slug

        # Also slugify if there's no slug provided.
        b = Addon(name=illegal_chars)
        b.clean_slug()
        assert b.slug.startswith("some-spaces-and"), b.slug

    def test_clean_slug_worst_case_scenario(self):
        long_slug = "this_is_a_very_long_slug_that_is_longer_than_thirty_chars"

        # Generate 100 addons with this very long slug. We should encounter the
        # worst case scenario where all the available clashes have been
        # avoided. Check the comment in addons.models.clean_slug, in the "else"
        # part of the "for" loop checking for available slugs not yet assigned.
        for i in range(100):
            Addon.objects.create(slug=long_slug)
        with self.assertRaises(RuntimeError):  # Fail on the 100th clash.
            Addon.objects.create(slug=long_slug)


class TestAddonManager(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/appversion', 'base/users',
                'base/addon_3615', 'addons/featured', 'addons/test_manager',
                'base/collections', 'base/featured',
                'bandwagon/featured_collections', 'base/addon_5299_gcal']

    def setUp(self):
        set_user(None)

    def test_featured(self):
        eq_(Addon.objects.featured(amo.FIREFOX).count(), 3)

    def test_listed(self):
        # We need this for the fixtures, but it messes up the tests.
        Addon.objects.get(pk=3615).update(disabled_by_user=True)
        # No continue as normal.
        Addon.objects.filter(id=5299).update(disabled_by_user=True)
        q = Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC)
        eq_(len(q.all()), 4)

        addon = q[0]
        eq_(addon.id, 2464)

        # Disabling hides it.
        addon.disabled_by_user = True
        addon.save()

        # Should be 3 now, since the one is now disabled.
        eq_(q.count(), 3)

        # If we search for public or unreviewed we find it.
        addon.disabled_by_user = False
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        eq_(q.count(), 3)
        eq_(Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC,
                                 amo.STATUS_UNREVIEWED).count(), 4)

        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        eq_(q.count(), 3)

    def test_public(self):
        public = Addon.objects.public()
        for a in public:
            assert_not_equal(
                a.id, 3, 'public() must not return unreviewed add-ons')

    def test_reviewed(self):
        for a in Addon.objects.reviewed():
            assert a.status in amo.REVIEWED_STATUSES, (a.id, a.status)

    def test_unreviewed(self):
        """
        Tests for unreviewed addons.
        """
        exp = Addon.objects.unreviewed()

        for addon in exp:
            assert addon.status in amo.UNREVIEWED_STATUSES, (
                'unreviewed() must return unreviewed addons.')

    def test_valid(self):
        addon = Addon.objects.get(pk=5299)
        addon.update(disabled_by_user=True)
        objs = Addon.objects.valid()

        for addon in objs:
            assert addon.status in amo.LISTED_STATUSES
            assert not addon.disabled_by_user

    def test_valid_disabled_by_user(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        addon = Addon.objects.get(pk=5299)
        addon.update(disabled_by_user=True)
        eq_(Addon.objects.valid_and_disabled_and_pending().count(), before)

    def test_valid_disabled_by_admin(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        addon = Addon.objects.get(pk=5299)
        addon.update(status=amo.STATUS_DISABLED)
        eq_(Addon.objects.valid_and_disabled_and_pending().count(), before)

    def test_invalid_deleted(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        addon = Addon.objects.get(pk=5299)
        addon.update(status=amo.STATUS_DELETED)
        eq_(Addon.objects.valid_and_disabled_and_pending().count(), before - 1)

    def test_valid_disabled_pending(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        amo.tests.addon_factory(status=amo.STATUS_PENDING)
        eq_(Addon.objects.valid_and_disabled_and_pending().count(), before + 1)

    def test_valid_disabled_version(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()

        # Add-on, no version. Doesn't count.
        addon = amo.tests.addon_factory()
        addon.update(_current_version=None, _signal=False)
        eq_(Addon.objects.valid_and_disabled_and_pending().count(), before)

        # Theme, no version. Counts.
        addon = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        addon.update(_current_version=None, _signal=False)
        eq_(Addon.objects.valid_and_disabled_and_pending().count(), before + 1)

    def test_new_featured(self):
        f = Addon.objects.featured(amo.FIREFOX)
        eq_(f.count(), 3)
        eq_(sorted(x.id for x in f),
            [2464, 7661, 15679])
        f = Addon.objects.featured(amo.THUNDERBIRD)
        assert not f.exists()


class TestAddonModels(amo.tests.TestCase):
    fixtures = ['base/apps',
                'base/appversion',
                'base/collections',
                'base/featured',
                'base/platforms',
                'base/users',
                'base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple.json',
                'base/addon_4594_a9',
                'base/addon_4664_twitterbar',
                'base/thunderbird',
                'addons/featured',
                'addons/invalid_latest_version',
                'addons/blacklisted',
                'bandwagon/featured_collections']

    def setUp(self):
        TranslationSequence.objects.create(id=99243)
        # TODO(andym): use Mock appropriately here.
        self.old_version = amo.FIREFOX.latest_version
        amo.FIREFOX.latest_version = '3.6.15'

    def tearDown(self):
        amo.FIREFOX.latest_version = self.old_version

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

    def test_latest_version(self):
        """
        Tests that we get the latest version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        eq_(a.latest_version.id, Version.objects.filter(addon=a).latest().id)

    def test_latest_version_no_version(self):
        Addon.objects.filter(pk=3723).update(_current_version=None)
        Version.objects.filter(addon=3723).delete()
        a = Addon.objects.get(pk=3723)
        eq_(a.latest_version, None)

    def test_latest_version_ignore_beta(self):
        a = Addon.objects.get(pk=3615)

        v1 = Version.objects.create(addon=a, version='1.0')
        File.objects.create(version=v1)
        eq_(a.latest_version.id, v1.id)

        v2 = Version.objects.create(addon=a, version='2.0beta')
        File.objects.create(version=v2, status=amo.STATUS_BETA)
        v2.save()
        eq_(a.latest_version.id, v1.id)  # Still should be f1

    def test_current_version_unsaved(self):
        a = Addon()
        a._current_version = Version()
        eq_(a.current_version, None)

    def test_latest_version_unsaved(self):
        a = Addon()
        a._latest_version = Version()
        eq_(a.latest_version, None)

    def test_current_beta_version(self):
        a = Addon.objects.get(pk=5299)
        eq_(a.current_beta_version.id, 50000)

    def _create_new_version(self, addon, status):
        av = addon.current_version.apps.all()[0]

        v = Version.objects.create(addon=addon, version='99')
        File.objects.create(status=status, version=v)

        ApplicationsVersions.objects.create(application_id=amo.FIREFOX.id,
                                            version=v, min=av.min, max=av.max)
        return v

    def test_compatible_version(self):
        a = Addon.objects.get(pk=3615)
        eq_(a.status, amo.STATUS_PUBLIC)

        v = self._create_new_version(addon=a, status=amo.STATUS_PUBLIC)

        eq_(a.compatible_version(amo.FIREFOX.id), v)

    def test_compatible_version_status(self):
        """
        Tests that `compatible_version()` won't return a lited version for a
        fully-reviewed add-on.
        """

        a = Addon.objects.get(pk=3615)
        eq_(a.status, amo.STATUS_PUBLIC)

        v = self._create_new_version(addon=a, status=amo.STATUS_LITE)

        assert a.current_version != v
        eq_(a.compatible_version(amo.FIREFOX.id), a.current_version)

    def test_transformer(self):
        addon = Addon.objects.get(pk=3615)
        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            addon._current_version
            addon._backup_version
            addon.latest_version

    def _delete(self):
        """Test deleting add-ons."""
        a = Addon.objects.get(pk=3615)
        a.name = u'é'
        a.delete('bye')
        eq_(len(mail.outbox), 1)
        assert BlacklistedGuid.objects.filter(guid=a.guid)

    def test_delete(self):
        deleted_count = Addon.with_deleted.count()
        self._delete()
        eq_(deleted_count, Addon.with_deleted.count())
        addon = Addon.with_deleted.get(pk=3615)
        eq_(addon.status, amo.STATUS_DELETED)
        eq_(addon.slug, None)
        eq_(addon.current_version, None)
        eq_(addon.app_slug, None)

    def _delete_url(self):
        """Test deleting addon has URL in the email."""
        a = Addon.objects.get(pk=4594)
        url = a.get_url_path()
        a.delete('bye')
        assert absolutify(url) in mail.outbox[0].body

    def test_delete_url(self):
        count = Addon.with_deleted.count()
        self._delete_url()
        eq_(count, Addon.with_deleted.count())

    def test_delete_reason(self):
        """Test deleting with a reason gives the reason in the mail."""
        reason = u'trêason'
        a = Addon.objects.get(pk=3615)
        a.name = u'é'
        eq_(len(mail.outbox), 0)
        a.delete(msg='bye', reason=reason)
        eq_(len(mail.outbox), 1)
        assert reason in mail.outbox[0].body

    def test_delete_status_gone_wild(self):
        """
        Test deleting add-ons where the higheststatus is zero, but there's a
        non-zero status.
        """
        count = Addon.objects.count()
        a = Addon.objects.get(pk=3615)
        a.status = amo.STATUS_UNREVIEWED
        a.highest_status = 0
        a.delete('bye')
        eq_(len(mail.outbox), 1)
        assert BlacklistedGuid.objects.filter(guid=a.guid)
        eq_(count, Addon.with_deleted.count())

    def test_delete_incomplete(self):
        """Test deleting incomplete add-ons."""
        count = Addon.with_deleted.count()
        a = Addon.objects.get(pk=3615)
        a.status = 0
        a.highest_status = 0
        a.save()
        a.delete(None)
        eq_(len(mail.outbox), 0)
        assert not BlacklistedGuid.objects.filter(guid=a.guid)
        eq_(Addon.with_deleted.count(), count - 1)

    def test_delete_searchengine(self):
        """
        Test deleting searchengines (which have no guids) should not barf up
        the deletion machine.
        """
        a = Addon.objects.get(pk=4594)
        a.delete('bye')
        eq_(len(mail.outbox), 1)

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

    def test_incompatible_asterix(self):
        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.create(application_id=amo.FIREFOX.id,
                                           version_int=version_int('5.*'),
                                           version='5.*')
        av.save()
        a = Addon.objects.get(pk=3615)
        eq_(a.incompatible_latest_apps(), [])

    def test_icon_url(self):
        """
        Tests for various icons.
        1. Test for an icon that exists.
        2. Test for default THEME icon.
        3. Test for default non-THEME icon.
        """
        a = Addon.objects.get(pk=3615)
        assert "/3/3615-32.png" in a.icon_url
        a = Addon.objects.get(pk=6704)
        a.icon_type = None
        assert a.icon_url.endswith('/icons/default-theme.png'), (
            'No match for %s' % a.icon_url)
        a = Addon.objects.get(pk=3615)
        a.icon_type = None

        assert a.icon_url.endswith('icons/default-32.png')

    def test_icon_url_default(self):
        a = Addon.objects.get(pk=3615)
        a.update(icon_type='')
        default = 'icons/default-32.png'
        eq_(a.icon_url.endswith(default), True)
        eq_(a.get_icon_url(32).endswith(default), True)
        eq_(a.get_icon_url(32, use_default=True).endswith(default), True)
        eq_(a.get_icon_url(32, use_default=False), None)

    def test_thumbnail_url(self):
        """
        Test for the actual thumbnail URL if it should exist, or the no-preview
        url.
        """
        a = Addon.objects.get(pk=4664)
        a.thumbnail_url.index('/previews/thumbs/20/20397.png?modified=')
        a = Addon.objects.get(pk=5299)
        assert a.thumbnail_url.endswith('/icons/no-preview.png'), (
            'No match for %s' % a.thumbnail_url)

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

    def test_is_public(self):
        # Public add-on.
        a = Addon.objects.get(pk=3615)
        assert a.is_public(), 'public add-on should not be is_pulic()'

        # Public, disabled add-on.
        a.disabled_by_user = True
        assert not a.is_public(), (
            'public, disabled add-on should not be is_public()')

        # Lite add-on.
        a.status = amo.STATUS_LITE
        a.disabled_by_user = False
        assert not a.is_public(), 'lite add-on should not be is_public()'

        # Unreviewed add-on.
        a.status = amo.STATUS_UNREVIEWED
        assert not a.is_public(), 'unreviewed add-on should not be is_public()'

        # Unreviewed, disabled add-on.
        a.status = amo.STATUS_UNREVIEWED
        a.disabled_by_user = True
        assert not a.is_public(), (
            'unreviewed, disabled add-on should not be is_public()')

    def test_is_no_restart(self):
        a = Addon.objects.get(pk=3615)
        f = a.current_version.all_files[0]
        eq_(f.no_restart, False)
        eq_(a.is_no_restart(), False)

        f.update(no_restart=True)
        eq_(Addon.objects.get(pk=3615).is_no_restart(), True)

        a.versions.all().delete()
        a._current_version = None
        eq_(a.is_no_restart(), False)

    def test_is_featured(self):
        """Test if an add-on is globally featured"""
        a = Addon.objects.get(pk=1003)
        assert a.is_featured(amo.FIREFOX, 'en-US'), (
            'globally featured add-on not recognized')

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

    def newlines_helper(self, string_before):
        addon = Addon.objects.get(pk=3615)
        addon.privacy_policy = string_before
        addon.save()
        return addon.privacy_policy.localized_string_clean

    def test_newlines_normal(self):
        before = ("Paragraph one.\n"
                  "This should be on the very next line.\n\n"
                  "Should be two nl's before this line.\n\n\n"
                  "Should be three nl's before this line.\n\n\n\n"
                  "Should be four nl's before this line.")

        after = before  # Nothing special; this shouldn't change.

        eq_(self.newlines_helper(before), after)

    def test_newlines_ul(self):
        before = ("<ul>\n\n"
                  "<li>No nl's between the ul and the li.</li>\n\n"
                  "<li>No nl's between li's.\n\n"
                  "But there should be two before this line.</li>\n\n"
                  "</ul>")

        after = ("<ul>"
                 "<li>No nl's between the ul and the li.</li>"
                 "<li>No nl's between li's.\n\n"
                 "But there should be two before this line.</li>"
                 "</ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_ul_tight(self):
        before = ("There should be one nl between this and the ul.\n"
                  "<ul><li>test</li><li>test</li></ul>\n"
                  "There should be no nl's above this line.")

        after = ("There should be one nl between this and the ul.\n"
                 "<ul><li>test</li><li>test</li></ul>"
                 "There should be no nl's above this line.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_ul_loose(self):
        before = ("There should be two nl's between this and the ul.\n\n"
                  "<ul><li>test</li><li>test</li></ul>\n\n"
                  "There should be one nl above this line.")

        after = ("There should be two nl's between this and the ul.\n\n"
                 "<ul><li>test</li><li>test</li></ul>\n"
                 "There should be one nl above this line.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_blockquote_tight(self):
        before = ("There should be one nl below this.\n"
                  "<blockquote>Hi</blockquote>\n"
                  "There should be no nl's above this.")

        after = ("There should be one nl below this.\n"
                 "<blockquote>Hi</blockquote>"
                 "There should be no nl's above this.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_blockquote_loose(self):
        before = ("There should be two nls below this.\n\n"
                  "<blockquote>Hi</blockquote>\n\n"
                  "There should be one nl above this.")

        after = ("There should be two nls below this.\n\n"
                 "<blockquote>Hi</blockquote>\n"
                 "There should be one nl above this.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_inline(self):
        before = ("If we end a paragraph w/ a <b>non-block-level tag</b>\n\n"
                  "<b>The newlines</b> should be kept")

        after = before  # Should stay the same

        eq_(self.newlines_helper(before), after)

    def test_newlines_code_inline(self):
        before = ("Code tags aren't blocks.\n\n"
                  "<code>alert(test);</code>\n\n"
                  "See?")

        after = before  # Should stay the same

        eq_(self.newlines_helper(before), after)

    def test_newlines_li_newlines(self):
        before = ("<ul><li>\nxx</li></ul>")
        after = ("<ul><li>xx</li></ul>")
        eq_(self.newlines_helper(before), after)

        before = ("<ul><li>xx\n</li></ul>")
        after = ("<ul><li>xx</li></ul>")
        eq_(self.newlines_helper(before), after)

        before = ("<ul><li>xx\nxx</li></ul>")
        after = ("<ul><li>xx\nxx</li></ul>")
        eq_(self.newlines_helper(before), after)

        before = ("<ul><li></li></ul>")
        after = ("<ul><li></li></ul>")
        eq_(self.newlines_helper(before), after)

        # All together now
        before = ("<ul><li>\nxx</li> <li>xx\n</li> <li>xx\nxx</li> "
                  "<li></li>\n</ul>")

        after = ("<ul><li>xx</li> <li>xx</li> <li>xx\nxx</li> "
                 "<li></li></ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag(self):
        before = ("This is a <b></b> test!")
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag_nested(self):
        before = ("This is a <b><i></i></b> test!")
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_empty_tag_block_nested(self):
        b = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>\ntest.")
        a = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>test.")

        eq_(self.newlines_helper(b), a)

    def test_newlines_empty_tag_block_nested_spaced(self):
        before = ("Test.\n\n<blockquote>\n\n<ul>\n\n<li>"
                  "</li>\n\n</ul>\n\n</blockquote>\ntest.")
        after = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>test.")

        eq_(self.newlines_helper(before), after)

    def test_newlines_li_newlines_inline(self):
        before = ("<ul><li>\n<b>test\ntest\n\ntest</b>\n</li>"
                  "<li>Test <b>test</b> test.</li></ul>")

        after = ("<ul><li><b>test\ntest\n\ntest</b></li>"
                 "<li>Test <b>test</b> test.</li></ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_li_all_inline(self):
        before = ("Test with <b>no newlines</b> and <code>block level "
                  "stuff</code> to see what happens.")

        after = before  # Should stay the same

        eq_(self.newlines_helper(before), after)

    def test_newlines_spaced_blocks(self):
        before = ("<blockquote>\n\n<ul>\n\n<li>\n\ntest\n\n</li>\n\n"
                  "</ul>\n\n</blockquote>")

        after = "<blockquote><ul><li>test</li></ul></blockquote>"

        eq_(self.newlines_helper(before), after)

    def test_newlines_spaced_inline(self):
        before = "Line.\n\n<b>\nThis line is bold.\n</b>\n\nThis isn't."
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_nested_inline(self):
        before = "<b>\nThis line is bold.\n\n<i>This is also italic</i></b>"
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_xss_script(self):
        before = "<script>\n\nalert('test');\n</script>"
        after = "&lt;script&gt;\n\nalert('test');\n&lt;/script&gt;"

        eq_(self.newlines_helper(before), after)

    def test_newlines_xss_inline(self):
        before = "<b onclick=\"alert('test');\">test</b>"
        after = "<b>test</b>"

        eq_(self.newlines_helper(before), after)

    @patch('amo.helpers.urlresolvers.get_outgoing_url')
    def test_newlines_attribute_link_doublequote(self, mock_get_outgoing_url):
        mock_get_outgoing_url.return_value = 'http://google.com'
        before = '<a href="http://google.com">test</a>'

        parsed = self.newlines_helper(before)

        assert 'rel="nofollow"' in parsed

    def test_newlines_attribute_singlequote(self):
        before = "<abbr title='laugh out loud'>lol</abbr>"
        after = '<abbr title="laugh out loud">lol</abbr>'

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_doublequote(self):
        before = '<abbr title="laugh out loud">lol</abbr>'
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_nestedquotes_doublesingle(self):
        before = '<abbr title="laugh \'out\' loud">lol</abbr>'
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_attribute_nestedquotes_singledouble(self):
        before = '<abbr title=\'laugh "out" loud\'>lol</abbr>'
        after = before

        eq_(self.newlines_helper(before), after)

    def test_newlines_unclosed_b(self):
        before = ("<b>test")
        after = ("<b>test</b>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_unclosed_b_wrapped(self):
        before = ("This is a <b>test")
        after = ("This is a <b>test</b>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_unclosed_li(self):
        before = ("<ul><li>test</ul>")
        after = ("<ul><li>test</li></ul>")

        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_faketag(self):
        before = "<madonna"
        after = ""

        eq_(self.newlines_helper(before), after)

    def test_newlines_correct_faketag(self):
        before = "<madonna>"
        after = "&lt;madonna&gt;"

        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_tag(self):
        before = "<strong"
        after = ""

        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_faketag_surrounded(self):
        before = "This is a <test of bleach"
        after = 'This is a'
        eq_(self.newlines_helper(before), after)

    def test_newlines_malformed_tag_surrounded(self):
        before = "This is a <strong of bleach"
        after = "This is a"
        eq_(self.newlines_helper(before), after)

    def test_newlines_less_than(self):
        before = "3 < 5"
        after = "3 &lt; 5"

        eq_(self.newlines_helper(before), after)

    def test_newlines_less_than_tight(self):
        before = "abc 3<5 def"
        after = "abc 3&lt;5 def"

        eq_(self.newlines_helper(before), after)

    def test_app_numeric_slug(self):
        cat = Category.objects.get(id=22)
        cat.slug = 123
        with self.assertRaises(ValidationError):
            cat.full_clean()

    def test_app_categories(self):
        addon = lambda: Addon.objects.get(pk=3615)

        c22 = Category.objects.get(id=22)
        c22.name = 'CCC'
        c22.save()
        c23 = Category.objects.get(id=23)
        c23.name = 'BBB'
        c23.save()
        c24 = Category.objects.get(id=24)
        c24.name = 'AAA'
        c24.save()

        cats = addon().all_categories
        eq_(cats, [c22, c23, c24])
        for cat in cats:
            eq_(cat.application.id, amo.FIREFOX.id)

        cats = [c24, c23, c22]
        app_cats = [(amo.FIREFOX, cats)]
        eq_(addon().app_categories, app_cats)

        tb = Application.objects.get(id=amo.THUNDERBIRD.id)
        c = Category(application=tb, name='XXX', type=addon().type, count=1,
                     weight=1)
        c.save()
        AddonCategory.objects.create(addon=addon(), category=c)
        c24.save()  # Clear the app_categories cache.
        app_cats += [(amo.THUNDERBIRD, [c])]
        eq_(addon().app_categories, app_cats)

    def test_app_categories_sunbird(self):
        get_addon = lambda: Addon.objects.get(pk=3615)
        addon = get_addon()

        # This add-on is already associated with three Firefox categories.
        cats = sorted(addon.categories.all(), key=lambda x: x.name)
        eq_(addon.app_categories, [(amo.FIREFOX, cats)])

        # Associate this add-on with a Sunbird category.
        a = Application.objects.create(id=amo.SUNBIRD.id)
        c2 = Category.objects.create(application=a, type=amo.ADDON_EXTENSION,
                                     name='Sunny D')
        AddonCategory.objects.create(addon=addon, category=c2)

        # Sunbird category should be excluded.
        eq_(get_addon().app_categories, [(amo.FIREFOX, cats)])

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

    def test_takes_contributions(self):
        a = Addon(status=amo.STATUS_PUBLIC, wants_contributions=True,
                  paypal_id='$$')
        assert a.takes_contributions

        a.status = amo.STATUS_UNREVIEWED
        assert not a.takes_contributions
        a.status = amo.STATUS_PUBLIC

        a.wants_contributions = False
        assert not a.takes_contributions
        a.wants_contributions = True

        a.paypal_id = None
        assert not a.takes_contributions

        a.charity_id = 12
        assert a.takes_contributions

    def test_show_beta(self):
        # Addon.current_beta_version will be empty, so show_beta is False.
        a = Addon(status=amo.STATUS_PUBLIC)
        assert not a.show_beta

    @patch('addons.models.Addon.current_beta_version')
    def test_show_beta_with_beta_version(self, beta_mock):
        beta_mock.return_value = object()
        # Fake current_beta_version to return something truthy.
        a = Addon(status=amo.STATUS_PUBLIC)
        assert a.show_beta

        # We have a beta version but status has to be public.
        a.status = amo.STATUS_UNREVIEWED
        assert not a.show_beta

    def test_update_logs(self):
        addon = Addon.objects.get(id=3615)
        set_user(UserProfile.objects.all()[0])
        addon.versions.all().delete()

        entries = ActivityLog.objects.all()
        eq_(entries[0].action, amo.LOG.CHANGE_STATUS.id)

    def test_can_request_review_waiting_period(self):
        now = datetime.now()
        a = Addon.objects.create(type=1)
        v = Version.objects.create(addon=a)
        # The first LITE version is only 5 days old, no dice.
        first_f = File.objects.create(status=amo.STATUS_LITE, version=v)
        first_f.update(datestatuschanged=now - timedelta(days=5),
                       created=now - timedelta(days=20))
        # TODO(andym): can this go in Addon.objects.create? bug 618444
        a.update(status=amo.STATUS_LITE)
        eq_(a.can_request_review(), ())

        # Now the first LITE is > 10 days old, change can happen.
        first_f.update(datestatuschanged=now - timedelta(days=11))
        # Add a second file, to be sure that we test the date
        # of the first created file.
        second_f = File.objects.create(status=amo.STATUS_LITE, version=v)
        second_f.update(datestatuschanged=now - timedelta(days=5))
        eq_(a.status, amo.STATUS_LITE)
        eq_(a.can_request_review(), (amo.STATUS_PUBLIC,))

    def test_days_until_full_nomination(self):
        # Normalize to 12am for reliable day subtraction:
        now = datetime.now().date()
        a = Addon.objects.create(type=1)
        v = Version.objects.create(addon=a)
        f = File.objects.create(status=amo.STATUS_LITE, version=v)
        a.update(status=amo.STATUS_LITE)
        f.update(datestatuschanged=now - timedelta(days=4))
        eq_(a.days_until_full_nomination(), 6)

        f.update(datestatuschanged=now - timedelta(days=1))
        eq_(a.days_until_full_nomination(), 9)

        f.update(datestatuschanged=now - timedelta(days=10))
        eq_(a.days_until_full_nomination(), 0)

        f.update(datestatuschanged=now)
        eq_(a.days_until_full_nomination(), 10)

        # Only calculate days from first submitted version:
        f.update(datestatuschanged=now - timedelta(days=2),
                 created=now - timedelta(days=2))
        # Ignore this one:
        f2 = File.objects.create(status=amo.STATUS_LITE, version=v)
        f2.update(datestatuschanged=now - timedelta(days=1),
                  created=now - timedelta(days=1))
        eq_(a.days_until_full_nomination(), 8)

        # Wrong status:
        f.update(datestatuschanged=now - timedelta(days=4))
        a.update(status=amo.STATUS_PUBLIC)
        eq_(a.days_until_full_nomination(), 0)

    def setup_files(self, status):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=status, version=version)
        return addon, version

    def test_no_change_disabled_user(self):
        addon, version = self.setup_files(amo.STATUS_UNREVIEWED)
        addon.update(status=amo.STATUS_PUBLIC)
        addon.update(disabled_by_user=True)
        version.save()
        eq_(addon.status, amo.STATUS_PUBLIC)
        assert addon.is_disabled

    def test_no_change_disabled(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        addon.update(status=amo.STATUS_DISABLED)
        version.save()
        eq_(addon.status, amo.STATUS_DISABLED)
        assert addon.is_disabled

    def test_no_change_deleted(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        addon.update(status=amo.STATUS_DELETED)
        version.save()
        eq_(addon.status, amo.STATUS_DELETED)
        assert addon.is_deleted

    def test_can_alter_in_prelim(self):
        addon, version = self.setup_files(amo.STATUS_LITE)
        addon.update(status=amo.STATUS_LITE)
        version.save()
        eq_(addon.status, amo.STATUS_LITE)

    def test_removing_public(self):
        addon, version = self.setup_files(amo.STATUS_UNREVIEWED)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        eq_(addon.status, amo.STATUS_UNREVIEWED)

    def test_removing_public_with_prelim(self):
        addon, version = self.setup_files(amo.STATUS_LITE)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        eq_(addon.status, amo.STATUS_LITE)

    def test_can_request_review_no_files(self):
        addon = Addon.objects.get(pk=3615)
        addon.versions.all()[0].files.all().delete()
        eq_(addon.can_request_review(), ())

    def test_can_request_review_rejected(self):
        addon = Addon.objects.get(pk=3615)
        addon.latest_version.files.update(status=amo.STATUS_DISABLED)
        eq_(addon.can_request_review(), ())

    def check(self, status, exp, kw={}):
        addon = Addon.objects.get(pk=3615)
        changes = {'status': status, 'disabled_by_user': False}
        changes.update(**kw)
        addon.update(**changes)
        eq_(addon.can_request_review(), exp)

    def test_can_request_review_null(self):
        self.check(amo.STATUS_NULL, (amo.STATUS_LITE, amo.STATUS_PUBLIC))

    def test_can_request_review_null_disabled(self):
        self.check(amo.STATUS_NULL, (), {'disabled_by_user': True})

    def test_can_request_review_unreviewed(self):
        self.check(amo.STATUS_UNREVIEWED, (amo.STATUS_PUBLIC,))

    def test_can_request_review_nominated(self):
        self.check(amo.STATUS_NOMINATED, (amo.STATUS_LITE,))

    def test_can_request_review_public(self):
        self.check(amo.STATUS_PUBLIC, ())

    def test_can_request_review_disabled(self):
        self.check(amo.STATUS_DISABLED, ())

    def test_can_request_review_deleted(self):
        self.check(amo.STATUS_DELETED, ())

    def test_can_request_review_lite(self):
        self.check(amo.STATUS_LITE, (amo.STATUS_PUBLIC,))

    def test_can_request_review_lite_and_nominated(self):
        self.check(amo.STATUS_LITE_AND_NOMINATED, ())

    def test_can_request_review_purgatory(self):
        self.check(amo.STATUS_PURGATORY, (amo.STATUS_LITE, amo.STATUS_PUBLIC,))

    def test_none_homepage(self):
        # There was an odd error when a translation was set to None.
        Addon.objects.create(homepage=None, type=amo.ADDON_EXTENSION)

    def test_slug_isdigit(self):
        a = Addon.objects.create(type=1, name='xx', slug='123')
        eq_(a.slug, '123~')

        a.slug = '44'
        a.save()
        eq_(a.slug, '44~')

    def test_slug_isblacklisted(self):
        # When an addon is uploaded, it doesn't use the form validation,
        # so we'll just mangle the slug if its blacklisted.
        a = Addon.objects.create(type=1, name='xx', slug='validate')
        eq_(a.slug, 'validate~')

        a.slug = 'validate'
        a.save()
        eq_(a.slug, 'validate~')

    def delete(self):
        addon = Addon.objects.get(id=3615)
        eq_(len(mail.outbox), 0)
        addon.delete('so long and thanks for all the fish')
        eq_(len(mail.outbox), 1)

    def test_delete_to(self):
        self.delete()
        eq_(mail.outbox[0].to, [settings.FLIGTAR])

    def test_delete_by(self):
        try:
            user = Addon.objects.get(id=3615).authors.all()[0]
            set_user(user)
            self.delete()
            assert 'DELETED BY: 55021' in mail.outbox[0].body
        finally:
            set_user(None)

    def test_delete_by_unknown(self):
        self.delete()
        assert 'DELETED BY: Unknown' in mail.outbox[0].body

    def test_view_source(self):
        # view_source should default to True.
        a = Addon.objects.create(type=1)
        assert a.view_source

    @patch('files.models.File.hide_disabled_file')
    def test_admin_disabled_file_hidden(self, hide_mock):
        a = Addon.objects.get(id=3615)
        a.status = amo.STATUS_PUBLIC
        a.save()
        assert not hide_mock.called

        a.status = amo.STATUS_DISABLED
        a.save()
        assert hide_mock.called

    @patch('files.models.File.hide_disabled_file')
    def test_user_disabled_file_hidden(self, hide_mock):
        a = Addon.objects.get(id=3615)
        a.disabled_by_user = False
        a.save()
        assert not hide_mock.called

        a.disabled_by_user = True
        a.save()
        assert hide_mock.called

    def test_set_nomination(self):
        a = Addon.objects.get(id=3615)
        for s in (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED):
            a.update(status=amo.STATUS_NULL)
            a.versions.latest().update(nomination=None)
            a.update(status=s)
            assert a.versions.latest().nomination

    def test_new_version_inherits_nomination(self):
        a = Addon.objects.get(id=3615)
        ver = 10
        for st in (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED):
            a.update(status=st)
            old_ver = a.versions.latest()
            v = Version.objects.create(addon=a, version=str(ver))
            eq_(v.nomination, old_ver.nomination)
            ver += 1

    def test_beta_version_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        a.update(status=amo.STATUS_NULL)
        v = Version.objects.create(addon=a, version='1.0')
        v.nomination = None
        v.save()
        a.update(status=amo.STATUS_NOMINATED)
        File.objects.create(version=v, status=amo.STATUS_BETA,
                            filename='foobar.xpi')
        v.version = '1.1'
        v.save()
        eq_(v.nomination, None)

    def test_lone_version_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        for v in Version.objects.all():
            v.delete()
        v = Version.objects.create(addon=a, version='1.0')
        eq_(v.nomination, None)

    def test_reviewed_addon_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        ver = 10
        for st in (amo.STATUS_PUBLIC, amo.STATUS_BETA, amo.STATUS_NULL):
            a.update(status=st)
            v = Version.objects.create(addon=a, version=str(ver))
            eq_(v.nomination, None)
            ver += 1

    def test_nomination_no_version(self):
        # Check that the on_change method still works if there are no versions.
        a = Addon.objects.get(id=3615)
        a.versions.all().delete()
        a.update(status=amo.STATUS_NOMINATED)

    def test_nomination_already_set(self):
        addon = Addon.objects.get(id=3615)
        earlier = datetime.today() - timedelta(days=2)
        addon.versions.latest().update(nomination=earlier)
        addon.update(status=amo.STATUS_NOMINATED)
        eq_(addon.versions.latest().nomination.date(), earlier.date())

    def test_new_version_of_under_review_addon_does_not_reset_nomination(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        # Cheating date to make sure we don't have a date on the same second
        # the code we test is running.
        past = self.days_ago(1)
        version.update(nomination=past, created=past, modified=past)
        # This is a preliminary review.
        addon.update(status=amo.STATUS_UNREVIEWED)
        current_nomination = addon.versions.latest().nomination
        assert current_nomination
        version = Version.objects.create(addon=addon)
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        eq_(addon.versions.latest().nomination, current_nomination)

    def test_nomination_not_reset_if_changing_review_process_under_review(self):
        """
        When under review, adding a new version should not reset nomination.
        """
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        # Cheating date to make sure we don't have a date on the same second
        # the code we test is running.
        past = self.days_ago(1)
        version.update(nomination=past, created=past, modified=past)
        # This is a preliminary review.
        addon.update(status=amo.STATUS_UNREVIEWED)
        current_nomination = addon.versions.latest().nomination
        assert current_nomination
        # Now switch to a full review.
        addon.update(status=amo.STATUS_NOMINATED)
        eq_(addon.versions.latest().nomination, current_nomination)
        # Then again to a preliminary.
        addon.update(status=amo.STATUS_UNREVIEWED)
        eq_(addon.versions.latest().nomination, current_nomination)

    def test_new_version_of_public_addon_should_reset_nomination(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=amo.STATUS_LITE, version=version)
        # The addon has been prelimarily reviewed.
        addon.update(status=amo.STATUS_LITE)
        # Cheating to make sure we don't have a date on the same second
        # of the running code.
        past = self.days_ago(1)
        version.update(nomination=past, created=past, modified=past)
        old_nomination = addon.versions.latest().nomination
        assert old_nomination

        # Update again, but without a new version.
        addon.update(status=amo.STATUS_LITE)
        # Check that nomination has been reset.
        eq_(addon.versions.latest().nomination, old_nomination)

        # Now create a new version with an attached file, and update status.
        version = Version.objects.create(addon=addon, version="0.2")
        assert version.nomination is None
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        new_nomination = addon.versions.latest().nomination
        assert new_nomination
        assert_not_equal(new_nomination, old_nomination)

    def test_new_version_of_fully_reviewed_addon_should_reset_nomination(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=amo.STATUS_PUBLIC, version=version)
        # The addon has been fully reviewed.
        addon.update(status=amo.STATUS_PUBLIC)
        # Cheating to make sure we don't have a date on the same second
        # of the running code.
        past = self.days_ago(1)
        version.update(nomination=past, created=past, modified=past)
        old_nomination = addon.versions.latest().nomination
        assert old_nomination

        # Now create a new version with an attached file, and update status.
        version = Version.objects.create(addon=addon, version="0.2")
        assert version.nomination is None
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        new_nomination = addon.versions.latest().nomination
        assert new_nomination
        assert_not_equal(new_nomination, old_nomination)

    def test_category_transform(self):
        addon = Addon.objects.get(id=3615)
        cats = addon.categories.filter(application=amo.FIREFOX.id)
        names = [c.name for c in cats]
        assert addon.get_category(amo.FIREFOX.id).name in names

    def test_binary_property(self):
        addon = Addon.objects.get(id=3615)
        file = addon.current_version.files.all()[0]
        file.update(binary=True)
        eq_(addon.binary, True)

    def test_binary_components_property(self):
        addon = Addon.objects.get(id=3615)
        file = addon.current_version.files.all()[0]
        file.update(binary_components=True)
        eq_(addon.binary_components, True)


class TestAddonDelete(amo.tests.TestCase):

    def test_cascades(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

        AddonCategory.objects.create(addon=addon,
            category=Category.objects.create(type=amo.ADDON_EXTENSION))
        AddonDependency.objects.create(addon=addon,
            dependent_addon=addon)
        AddonDeviceType.objects.create(addon=addon,
            device_type=DEVICE_TYPES.keys()[0])
        AddonRecommendation.objects.create(addon=addon,
            other_addon=addon, score=0)
        AddonUser.objects.create(addon=addon,
            user=UserProfile.objects.create())
        AppSupport.objects.create(addon=addon,
            app=Application.objects.create())
        CompatOverride.objects.create(addon=addon)
        FrozenAddon.objects.create(addon=addon)
        Persona.objects.create(addon=addon, persona_id=0)
        Preview.objects.create(addon=addon)

        AddonLog.objects.create(addon=addon,
            activity_log=ActivityLog.objects.create(action=0))
        RssKey.objects.create(addon=addon)
        SubmitStep.objects.create(addon=addon, step=0)

        # This should not throw any FK errors if all the cascades work.
        addon.delete()

    def test_review_delete(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_PUBLIC,
                                     highest_status=amo.STATUS_PUBLIC)

        review = Review.objects.create(addon=addon, rating=1, body='foo',
                                       user=UserProfile.objects.create())

        flag = ReviewFlag(review=review)

        addon.delete()

        eq_(Addon.with_deleted.filter(pk=addon.pk).exists(), True)
        eq_(Review.objects.filter(pk=review.pk).exists(), False)
        eq_(ReviewFlag.objects.filter(pk=flag.pk).exists(), False)


class TestUpdateStatus(amo.tests.TestCase):
    fixtures = ['base/platforms', ]

    def test_no_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        eq_(Addon.objects.no_cache().get(pk=addon.pk).status, amo.STATUS_UNREVIEWED)
        Version.objects.create(addon=addon)
        eq_(Addon.objects.no_cache().get(pk=addon.pk).status, amo.STATUS_NULL)

    def test_no_valid_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = Version.objects.create(addon=addon)
        f = File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        eq_(Addon.objects.no_cache().get(pk=addon.pk).status, amo.STATUS_UNREVIEWED)
        f.status = amo.STATUS_DISABLED
        f.save()
        eq_(Addon.objects.no_cache().get(pk=addon.pk).status, amo.STATUS_NULL)


class TestGetVersion(amo.tests.TestCase):
    fixtures = ['base/addon_3615', ]

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def new_version(self, status):
        version = Version.objects.create(addon=self.addon)
        File.objects.create(version=version, status=status)
        return version

    def test_public_new_lite_version(self):
        self.new_version(amo.STATUS_LITE)
        eq_(self.addon.get_version(), self.version)

    def test_public_new_nominated_version(self):
        self.new_version(amo.STATUS_NOMINATED)
        eq_(self.addon.get_version(), self.version)

    def test_public_new_public_version(self):
        v = self.new_version(amo.STATUS_PUBLIC)
        eq_(self.addon.get_version(), v)

    def test_public_new_unreviewed_version(self):
        self.new_version(amo.STATUS_UNREVIEWED)
        eq_(self.addon.get_version(), self.version)

    def test_lite_new_unreviewed_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.new_version(amo.STATUS_UNREVIEWED)
        eq_(self.addon.get_version(), self.version)

    def test_lite_new_lan_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_LITE_AND_NOMINATED)
        eq_(self.addon.get_version(), v)

    def test_lite_new_lite_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_LITE)
        eq_(self.addon.get_version(), v)

    def test_lite_new_full_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_PUBLIC)
        eq_(self.addon.get_version(), v)

    def test_lan_new_lite_version(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        v = self.new_version(amo.STATUS_LITE)
        eq_(self.addon.get_version(), v)

    def test_lan_new_full_version(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        v = self.new_version(amo.STATUS_PUBLIC)
        eq_(self.addon.get_version(), v)

    def test_should_promote_previous_valid_version_if_latest_is_disabled(self):
        self.new_version(amo.STATUS_DISABLED)
        eq_(self.addon.get_version(), self.version)


class TestAddonGetURLPath(amo.tests.TestCase):

    def test_get_url_path(self):
        addon = Addon(slug='woo')
        eq_(addon.get_url_path(), '/en-US/firefox/addon/woo/')

    def test_get_url_path_more(self):
        addon = Addon(slug='yeah')
        eq_(addon.get_url_path(more=True),
            '/en-US/firefox/addon/yeah/more')


class TestAddonModelsFeatured(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/appversion', 'base/users',
                'addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured']

    def setUp(self):
        # Addon._featured keeps an in-process cache we need to clear.
        if hasattr(Addon, '_featured'):
            del Addon._featured

    def _test_featured_random(self):
        f = Addon.featured_random(amo.FIREFOX, 'en-US')
        eq_(sorted(f), [1001, 1003, 2464, 3481, 7661, 15679])
        f = Addon.featured_random(amo.FIREFOX, 'fr')
        eq_(sorted(f), [1001, 1003, 2464, 7661, 15679])
        f = Addon.featured_random(amo.THUNDERBIRD, 'en-US')
        eq_(f, [])

    def test_featured_random(self):
        self._test_featured_random()


class TestBackupVersion(amo.tests.TestCase):
    fixtures = ['addons/update', 'base/apps', 'base/appversion',
                'base/platforms']

    def setUp(self):
        self.version_1_2_0 = 105387
        self.addon = Addon.objects.get(pk=1865)
        set_user(None)

    def setup_new_version(self):
        for version in Version.objects.filter(pk__gte=self.version_1_2_0):
            appversion = version.apps.all()[0]
            appversion.min = AppVersion.objects.get(version='4.0b1')
            appversion.save()

    def test_no_backup_version(self):
        self.addon.update_version()
        eq_(self.addon.backup_version, None)
        eq_(self.addon.current_version.version, '1.2.2')

    def test_no_current_version(self):
        for v in Version.objects.all():
            v.delete()
        self.addon.update(_current_version=None)
        eq_(self.addon.backup_version, None)
        eq_(self.addon.current_version, None)

    def test_has_backup_version(self):
        self.setup_new_version()
        assert self.addon.update_version()
        eq_(self.addon.backup_version.version, '1.1.3')
        eq_(self.addon.current_version.version, '1.2.2')

    def test_backup_version(self):
        self.setup_new_version()
        assert self.addon.update_version()
        eq_(self.addon.backup_version.version, '1.1.3')

    def test_firefox_versions(self):
        self.setup_new_version()
        assert self.addon.update_version()
        backup = self.addon.backup_version.compatible_apps[amo.FIREFOX]
        eq_(backup.max.version, '3.7a5pre')
        eq_(backup.min.version, '3.0.12')
        current = self.addon.current_version.compatible_apps[amo.FIREFOX]
        eq_(current.max.version, '4.0b8pre')
        eq_(current.min.version, '3.0.12')

    def test_version_signals(self):
        self.setup_new_version()
        version = self.addon.versions.all()[0]
        assert not self.addon.backup_version
        version.save()
        assert Addon.objects.get(pk=1865).backup_version

    def test_update_version_theme(self):
        # Test versions do not get deleted when calling with theme.
        self.addon.update(type=amo.ADDON_PERSONA)
        assert not self.addon.update_version()
        assert self.addon._current_version

        # Test latest version copied to current version if no current version.
        self.addon.update(_current_version=None,
                          _latest_version=Version.objects.create(
                              addon=self.addon, version='0'),
                          _signal=False)
        assert self.addon.update_version()
        assert self.addon._current_version == self.addon._latest_version


class TestCategoryModel(amo.tests.TestCase):

    def test_category_url(self):
        """Every type must have a url path for its categories."""
        for t in amo.ADDON_TYPE.keys():
            if t == amo.ADDON_DICT:
                continue  # Language packs don't have categories.
            cat = Category(type=t, slug='omg')
            assert cat.get_url_path()


class TestPersonaModel(amo.tests.TestCase):
    fixtures = ['addons/persona']

    def setUp(self):
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.persona.header = 'header.png'
        self.persona.footer = 'footer.png'
        self.persona.save()
        modified = int(time.mktime(self.persona.addon.modified.timetuple()))
        self.p = lambda fn: '/15663/%s?%s' % (fn, modified)

    def test_image_urls(self):
        # AMO-uploaded themes have `persona_id=0`.
        self.persona.persona_id = 0
        self.persona.save()
        ok_(self.persona.thumb_url.endswith(self.p('preview.png')),
            self.persona.thumb_url)
        ok_(self.persona.icon_url.endswith(self.p('icon.png')),
            self.persona.icon_url)
        ok_(self.persona.preview_url.endswith(self.p('preview.png')),
            self.persona.preview_url)
        ok_(self.persona.header_url.endswith(self.p('header.png')),
            self.persona.header_url)
        ok_(self.persona.footer_url.endswith(self.p('footer.png')),
            self.persona.footer_url)

    def test_old_image_urls(self):
        ok_(self.persona.thumb_url.endswith(self.p('preview.jpg')),
            self.persona.thumb_url)
        ok_(self.persona.icon_url.endswith(self.p('preview_small.jpg')),
            self.persona.icon_url)
        ok_(self.persona.preview_url.endswith(self.p('preview_large.jpg')),
            self.persona.preview_url)
        ok_(self.persona.header_url.endswith(self.p('header.png')),
            self.persona.header_url)
        ok_(self.persona.footer_url.endswith(self.p('footer.png')),
            self.persona.footer_url)

    def test_update_url(self):
        with self.settings(LANGUAGE_CODE='fr', LANGUAGE_URL_MAP={}):
            url_ = self.persona.update_url
            ok_(url_.endswith('/fr/themes/update-check/15663'), url_)

    def test_json_data(self):
        self.persona.addon.all_categories = [Category(name='Yolo Art')]

        VAMO = 'https://vamo/%(locale)s/themes/update-check/%(id)d'

        with self.settings(LANGUAGE_CODE='fr',
                           LANGUAGE_URL_MAP={},
                           NEW_PERSONAS_UPDATE_URL=VAMO,
                           SITE_URL='https://omgsh.it'):
            data = self.persona.theme_data

            id_ = str(self.persona.addon.id)

            eq_(data['id'], id_)
            eq_(data['name'], unicode(self.persona.addon.name))
            eq_(data['accentcolor'], '#8d8d97')
            eq_(data['textcolor'], '#ffffff')
            eq_(data['category'], 'Yolo Art')
            eq_(data['author'], 'persona_author')
            eq_(data['description'], unicode(self.addon.description))

            assert data['headerURL'].startswith(
                '%s%s/header.png?' % (user_media_url('addons'), id_))
            assert data['footerURL'].startswith(
                '%s%s/footer.png?' % (user_media_url('addons'), id_))
            assert data['previewURL'].startswith(
                '%s%s/preview.jpg?' % (user_media_url('addons'), id_))
            assert data['iconURL'].startswith(
                '%s%s/preview_small.jpg?' % (user_media_url('addons'), id_))

            eq_(data['detailURL'],
                'https://omgsh.it%s' % self.persona.addon.get_url_path())
            eq_(data['updateURL'],
                'https://vamo/fr/themes/update-check/' + id_)
            eq_(data['version'], '1.0')


class TestPreviewModel(amo.tests.TestCase):
    fixtures = ['base/previews']

    def test_as_dict(self):
        expect = ['caption', 'full', 'thumbnail']
        reality = sorted(Preview.objects.all()[0].as_dict().keys())
        eq_(expect, reality)

    def test_filename(self):
        preview = Preview.objects.get(pk=24)
        eq_(preview.file_extension, 'png')
        preview.update(filetype='')
        eq_(preview.file_extension, 'png')
        preview.update(filetype='video/webm')
        eq_(preview.file_extension, 'webm')

    def test_filename_in_url(self):
        preview = Preview.objects.get(pk=24)
        preview.update(filetype='video/webm')
        assert 'png' in preview.thumbnail_path
        assert 'webm' in preview.image_path


class TestAddonRecommendations(amo.tests.TestCase):
    fixtures = ['base/addon-recs']

    def test_scores(self):
        ids = [5299, 1843, 2464, 7661, 5369]
        scores = AddonRecommendation.scores(ids)
        q = AddonRecommendation.objects.filter(addon__in=ids)
        for addon, recs in itertools.groupby(q, lambda x: x.addon_id):
            for rec in recs:
                eq_(scores[addon][rec.other_addon_id], rec.score)


class TestAddonDependencies(amo.tests.TestCase):
    fixtures = ['base/apps',
                'base/appversion',
                'base/platforms',
                'base/users',
                'base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple',
                'base/addon_4664_twitterbar']

    def test_dependencies(self):
        ids = [3615, 3723, 4664, 6704]
        addon = Addon.objects.get(id=5299)

        for dependent_id in ids:
            AddonDependency(addon=addon,
                dependent_addon=Addon.objects.get(id=dependent_id)).save()

        eq_(sorted([a.id for a in addon.dependencies.all()]), sorted(ids))
        eq_(list(a.dependencies.all()), a.all_dependencies)

    def test_unique_dependencies(self):
        a = Addon.objects.get(id=5299)
        b = Addon.objects.get(id=3615)
        AddonDependency.objects.create(addon=a, dependent_addon=b)
        try:
            AddonDependency.objects.create(addon=a, dependent_addon=b)
        except IntegrityError:
            pass
        eq_(list(a.dependencies.values_list('id', flat=True)), [3615])


class TestListedAddonTwoVersions(amo.tests.TestCase):
    fixtures = ['addons/listed-two-versions']

    def test_listed_two_versions(self):
        Addon.objects.get(id=2795)  # bug 563967


class TestFlushURLs(amo.tests.TestCase):
    fixtures = ['base/apps',
                'base/appversion',
                'base/platforms',
                'base/users',
                'base/addon_5579',
                'base/previews',
                'base/addon_4664_twitterbar',
                'addons/persona']

    def setUp(self):
        settings.ADDON_ICON_URL = (
            settings.STATIC_URL +
            'img/uploads/addon_icons/%s/%s-%s.png?modified=%s')
        settings.PREVIEW_THUMBNAIL_URL = (
            settings.STATIC_URL +
            'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
        settings.PREVIEW_FULL_URL = (
            settings.STATIC_URL +
            'img/uploads/previews/full/%s/%d.%s?modified=%d')
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


class TestAddonFromUpload(UploadTest):
    fixtures = ('base/apps', 'base/users')

    def setUp(self):
        super(TestAddonFromUpload, self).setUp()
        u = UserProfile.objects.get(pk=999)
        set_user(u)
        self.platform = Platform.objects.create(id=amo.PLATFORM_MAC.id)
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application_id=1, version=version)
        self.addCleanup(translation.deactivate)

    def manifest(self, basename):
        return os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                            'addons', basename)

    def test_blacklisted_guid(self):
        BlacklistedGuid.objects.create(guid='guid@xpi')
        with self.assertRaises(forms.ValidationError) as e:
            Addon.from_upload(self.get_upload('extension.xpi'),
                              [self.platform])
        eq_(e.exception.messages, ['Duplicate UUID found.'])

    def test_xpi_attributes(self):
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        eq_(addon.name, 'xpi name')
        eq_(addon.guid, 'guid@xpi')
        eq_(addon.type, amo.ADDON_EXTENSION)
        eq_(addon.status, amo.STATUS_NULL)
        eq_(addon.homepage, 'http://homepage.com')
        eq_(addon.summary, 'xpi description')
        eq_(addon.description, None)
        eq_(addon.slug, 'xpi-name')

    def test_xpi_version(self):
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        v = addon.versions.get()
        eq_(v.version, '0.1')
        eq_(v.files.get().platform_id, self.platform.id)
        eq_(v.files.get().status, amo.STATUS_UNREVIEWED)

    def test_xpi_for_multiple_platforms(self):
        platforms = [Platform.objects.get(pk=amo.PLATFORM_LINUX.id),
                     Platform.objects.get(pk=amo.PLATFORM_MAC.id)]
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  platforms)
        v = addon.versions.get()
        eq_(sorted([f.platform.id for f in v.all_files]),
            sorted([p.id for p in platforms]))

    def test_search_attributes(self):
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        eq_(addon.name, 'search tool')
        eq_(addon.guid, None)
        eq_(addon.type, amo.ADDON_SEARCH)
        eq_(addon.status, amo.STATUS_NULL)
        eq_(addon.homepage, None)
        eq_(addon.description, None)
        eq_(addon.slug, 'search-tool')
        eq_(addon.summary, 'Search Engine for Firefox')

    def test_search_version(self):
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        v = addon.versions.get()
        eq_(v.version, datetime.now().strftime('%Y%m%d'))
        eq_(v.files.get().platform_id, amo.PLATFORM_ALL.id)
        eq_(v.files.get().status, amo.STATUS_UNREVIEWED)

    def test_no_homepage(self):
        addon = Addon.from_upload(self.get_upload('extension-no-homepage.xpi'),
                                  [self.platform])
        eq_(addon.homepage, None)

    def test_default_locale(self):
        # Make sure default_locale follows the active translation.
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        eq_(addon.default_locale, 'en-US')

        translation.activate('es')
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        eq_(addon.default_locale, 'es')

REDIRECT_URL = 'http://outgoing.mozilla.org/v1/'


class TestCharity(amo.tests.TestCase):
    fixtures = ['base/charity.json']

    @patch.object(settings, 'REDIRECT_URL', REDIRECT_URL)
    def test_url(self):
        charity = Charity(name="a", paypal="b", url="http://foo.com")
        charity.save()
        assert charity.outgoing_url.startswith(REDIRECT_URL)

    @patch.object(settings, 'REDIRECT_URL', REDIRECT_URL)
    def test_url_foundation(self):
        foundation = Charity.objects.get(pk=amo.FOUNDATION_ORG)
        assert not foundation.outgoing_url.startswith(REDIRECT_URL)


class TestFrozenAddons(amo.tests.TestCase):

    def test_immediate_freeze(self):
        # Adding a FrozenAddon should immediately drop the addon's hotness.
        a = Addon.objects.create(type=1, hotness=22)
        FrozenAddon.objects.create(addon=a)
        eq_(Addon.objects.get(id=a.id).hotness, 0)


class TestRemoveLocale(amo.tests.TestCase):

    def test_remove(self):
        a = Addon.objects.create(type=1)
        a.name = {'en-US': 'woo', 'el': 'yeah'}
        a.description = {'en-US': 'woo', 'el': 'yeah', 'he': 'ola'}
        a.save()
        a.remove_locale('el')
        qs = (Translation.objects.filter(localized_string__isnull=False)
              .values_list('locale', flat=True))
        eq_(sorted(qs.filter(id=a.name_id)), ['en-US'])
        eq_(sorted(qs.filter(id=a.description_id)), ['en-US', 'he'])

    def test_remove_version_locale(self):
        addon = Addon.objects.create(type=amo.ADDON_THEME)
        version = Version.objects.create(addon=addon)
        version.releasenotes = {'fr': 'oui'}
        version.save()
        addon.remove_locale('fr')
        assert not (Translation.objects.filter(localized_string__isnull=False)
                               .values_list('locale', flat=True))


class TestUpdateNames(amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.addon.name = self.names = {'en-US': 'woo'}
        self.addon.save()

    def get_name(self, app, locale='en-US'):
        return Translation.objects.no_cache().get(id=app.name_id,
                                                  locale=locale)

    def check_names(self, names):
        """`names` in {locale: name} format."""
        for locale, localized_string in names.iteritems():
            eq_(self.get_name(self.addon, locale).localized_string,
                localized_string)

    def test_new_name(self):
        names = dict(self.names, **{'de': u'frü'})
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)

    def test_new_names(self):
        names = dict(self.names, **{'de': u'frü', 'es': u'eso'})
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)

    def test_remove_name_missing(self):
        names = dict(self.names, **{'de': u'frü', 'es': u'eso'})
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)
        # Now update without de to remove it.
        del names['de']
        self.addon.update_names(names)
        self.addon.save()
        names['de'] = None
        self.check_names(names)

    def test_remove_name_with_none(self):
        names = dict(self.names, **{'de': u'frü', 'es': u'eso'})
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)
        # Now update without de to remove it.
        names['de'] = None
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)

    def test_add_and_remove(self):
        names = dict(self.names, **{'de': u'frü', 'es': u'eso'})
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)
        # Now add a new locale and remove an existing one.
        names['de'] = None
        names['fr'] = u'oui'
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)

    def test_default_locale_change(self):
        names = dict(self.names, **{'de': u'frü', 'es': u'eso'})
        self.addon.default_locale = 'de'
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)
        addon = self.addon.reload()
        eq_(addon.default_locale, 'de')

    def test_default_locale_change_remove_old(self):
        names = dict(self.names, **{'de': u'frü', 'es': u'eso', 'en-US': None})
        self.addon.default_locale = 'de'
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(names)
        eq_(self.addon.reload().default_locale, 'de')

    def test_default_locale_removal_not_deleted(self):
        names = {'en-US': None}
        self.addon.update_names(names)
        self.addon.save()
        self.check_names(self.names)


class TestAddonWatchDisabled(amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon(type=amo.ADDON_THEME, disabled_by_user=False,
                           status=amo.STATUS_PUBLIC)
        self.addon.save()

    @patch('addons.models.File.objects.filter')
    def test_no_disabled_change(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.save()
        assert not mock.unhide_disabled_file.called
        assert not mock.hide_disabled_file.called

    @patch('addons.models.File.objects.filter')
    def test_disable_addon(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.update(disabled_by_user=True)
        assert not mock.unhide_disabled_file.called
        assert mock.hide_disabled_file.called

    @patch('addons.models.File.objects.filter')
    def test_admin_disable_addon(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.update(status=amo.STATUS_DISABLED)
        assert not mock.unhide_disabled_file.called
        assert mock.hide_disabled_file.called

    @patch('addons.models.File.objects.filter')
    def test_enable_addon(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.update(status=amo.STATUS_DISABLED)
        mock.reset_mock()
        self.addon.update(status=amo.STATUS_PUBLIC)
        assert mock.unhide_disabled_file.called
        assert not mock.hide_disabled_file.called


class TestSearchSignals(amo.tests.ESTestCase):
    test_es = True

    def setUp(self):
        super(TestSearchSignals, self).setUp()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.empty_index('default')

    def test_no_addons(self):
        eq_(Addon.search().count(), 0)

    def test_create(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo')
        self.refresh()
        eq_(Addon.search().count(), 1)
        eq_(Addon.search().query(name='woo')[0].id, addon.id)

    def test_update(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo')
        self.refresh()
        eq_(Addon.search().count(), 1)

        addon.name = 'yeah'
        addon.save()
        self.refresh()

        eq_(Addon.search().count(), 1)
        eq_(Addon.search().query(name='woo').count(), 0)
        eq_(Addon.search().query(name='yeah')[0].id, addon.id)

    def test_delete(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo')
        self.refresh()
        eq_(Addon.search().count(), 1)

        addon.delete('woo')
        self.refresh()
        eq_(Addon.search().count(), 0)


class TestLanguagePack(amo.tests.TestCase, amo.tests.AMOPaths):

    def setUp(self):
        super(TestLanguagePack, self).setUp()
        self.addon = amo.tests.addon_factory(type=amo.ADDON_LPAPP,
                                             status=amo.STATUS_PUBLIC)
        self.platform_all = Platform.objects.get(id=amo.PLATFORM_ALL.id)
        self.platform_mob = Platform.objects.create(id=amo.PLATFORM_ANDROID.id)
        self.version = self.addon.current_version

    def test_extract(self):
        File.objects.create(platform=self.platform_mob, version=self.version,
                            filename=self.xpi_path('langpack-localepicker'),
                            status=amo.STATUS_PUBLIC)
        assert self.addon.reload().get_localepicker()
        assert 'title=Select a language' in self.addon.get_localepicker()

    def test_extract_no_file(self):
        File.objects.create(platform=self.platform_mob, version=self.version,
                            filename=self.xpi_path('langpack'), status=amo.STATUS_PUBLIC)
        eq_(self.addon.reload().get_localepicker(), '')

    def test_extract_no_files(self):
        eq_(self.addon.get_localepicker(), '')

    def test_extract_not_language_pack(self):
        File.objects.create(platform=self.platform_mob, version=self.version,
                            filename=self.xpi_path('langpack-localepicker'),
                            status=amo.STATUS_PUBLIC)
        assert self.addon.reload().get_localepicker()
        self.addon.update(type=amo.ADDON_EXTENSION)
        eq_(self.addon.get_localepicker(), '')

    def test_extract_not_platform_mobile(self):
        File.objects.create(platform=self.platform_all, version=self.version,
                            filename=self.xpi_path('langpack-localepicker'),
                            status=amo.STATUS_PUBLIC)
        eq_(self.addon.reload().get_localepicker(), '')


class TestCompatOverride(amo.tests.TestCase):

    def setUp(self):
        self.app = Application.objects.create(id=1)

        one = CompatOverride.objects.create(guid='one')
        CompatOverrideRange.objects.create(compat=one, app=self.app)

        two = CompatOverride.objects.create(guid='two')
        CompatOverrideRange.objects.create(compat=two, app=self.app,
                                           min_version='1', max_version='2')
        CompatOverrideRange.objects.create(compat=two, app=self.app,
                                           min_version='1', max_version='2',
                                           min_app_version='3',
                                           max_app_version='4')

    def check(self, obj, **kw):
        """Check that key/value pairs in kw match attributes of obj."""
        for key, expected in kw.items():
            actual = getattr(obj, key)
            eq_(actual, expected, '[%s] %r != %r' % (key, actual, expected))

    def test_is_hosted(self):
        c = CompatOverride.objects.create(guid='a')
        assert not c.is_hosted()

        Addon.objects.create(type=1, guid='b')
        c = CompatOverride.objects.create(guid='b')
        assert c.is_hosted()

    def test_override_type(self):
        one = CompatOverride.objects.get(guid='one')

        # The default is incompatible.
        c = CompatOverrideRange.objects.create(compat=one, app_id=1)
        eq_(c.override_type(), 'incompatible')

        c = CompatOverrideRange.objects.create(compat=one, app_id=1, type=0)
        eq_(c.override_type(), 'compatible')

    def test_guid_match(self):
        # We hook up the add-on automatically if we see a matching guid.
        addon = Addon.objects.create(id=1, guid='oh yeah', type=1)
        c = CompatOverride.objects.create(guid=addon.guid)
        eq_(c.addon_id, addon.id)

        c = CompatOverride.objects.create(guid='something else')
        assert c.addon is None

    def test_transformer(self):
        compats = list(CompatOverride.objects
                       .transform(CompatOverride.transformer))
        ranges = list(CompatOverrideRange.objects.all())
        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            for c in compats:
                eq_(c.compat_ranges,
                    [r for r in ranges if r.compat_id == c.id])

    def test_collapsed_ranges(self):
        # Test that we get back the right structures from collapsed_ranges().
        c = CompatOverride.objects.get(guid='one')
        r = c.collapsed_ranges()

        eq_(len(r), 1)
        compat_range = r[0]
        self.check(compat_range, type='incompatible', min='0', max='*')

        eq_(len(compat_range.apps), 1)
        self.check(compat_range.apps[0], app=amo.FIREFOX, min='0', max='*')

    def test_collapsed_ranges_multiple_versions(self):
        c = CompatOverride.objects.get(guid='one')
        CompatOverrideRange.objects.create(compat=c, app_id=1,
                                           min_version='1', max_version='2',
                                           min_app_version='3',
                                           max_app_version='3.*')
        r = c.collapsed_ranges()

        eq_(len(r), 2)

        self.check(r[0], type='incompatible', min='0', max='*')
        eq_(len(r[0].apps), 1)
        self.check(r[0].apps[0], app=amo.FIREFOX, min='0', max='*')

        self.check(r[1], type='incompatible', min='1', max='2')
        eq_(len(r[1].apps), 1)
        self.check(r[1].apps[0], app=amo.FIREFOX, min='3', max='3.*')

    def test_collapsed_ranges_different_types(self):
        # If the override ranges have different types they should be separate
        # entries.
        c = CompatOverride.objects.get(guid='one')
        CompatOverrideRange.objects.create(compat=c, app_id=1, type=0,
                                           min_app_version='3',
                                           max_app_version='3.*')
        r = c.collapsed_ranges()

        eq_(len(r), 2)

        self.check(r[0], type='compatible', min='0', max='*')
        eq_(len(r[0].apps), 1)
        self.check(r[0].apps[0], app=amo.FIREFOX, min='3', max='3.*')

        self.check(r[1], type='incompatible', min='0', max='*')
        eq_(len(r[1].apps), 1)
        self.check(r[1].apps[0], app=amo.FIREFOX, min='0', max='*')

    def test_collapsed_ranges_multiple_apps(self):
        c = CompatOverride.objects.get(guid='two')
        r = c.collapsed_ranges()

        eq_(len(r), 1)
        compat_range = r[0]
        self.check(compat_range, type='incompatible', min='1', max='2')

        eq_(len(compat_range.apps), 2)
        self.check(compat_range.apps[0], app=amo.FIREFOX, min='0', max='*')
        self.check(compat_range.apps[1], app=amo.FIREFOX, min='3', max='4')

    def test_collapsed_ranges_multiple_versions_and_apps(self):
        c = CompatOverride.objects.get(guid='two')
        CompatOverrideRange.objects.create(min_version='5', max_version='6',
                                           compat=c, app_id=1)
        r = c.collapsed_ranges()

        eq_(len(r), 2)
        self.check(r[0], type='incompatible', min='1', max='2')

        eq_(len(r[0].apps), 2)
        self.check(r[0].apps[0], app=amo.FIREFOX, min='0', max='*')
        self.check(r[0].apps[1], app=amo.FIREFOX, min='3', max='4')

        self.check(r[1], type='incompatible', min='5', max='6')
        eq_(len(r[1].apps), 1)
        self.check(r[1].apps[0], app=amo.FIREFOX, min='0', max='*')


class TestIncompatibleVersions(amo.tests.TestCase):

    def setUp(self):
        self.app = Application.objects.create(id=amo.FIREFOX.id)
        self.addon = Addon.objects.create(guid='r@b', type=amo.ADDON_EXTENSION)

    def test_signals_min(self):
        eq_(IncompatibleVersions.objects.count(), 0)

        c = CompatOverride.objects.create(guid='r@b')
        CompatOverrideRange.objects.create(compat=c, app=self.app,
                                           min_version='0',
                                           max_version='1.0')

        # Test the max version matched.
        version1 = Version.objects.create(id=2, addon=self.addon,
                                          version='1.0')
        eq_(IncompatibleVersions.objects.filter(version=version1).count(), 1)
        eq_(IncompatibleVersions.objects.count(), 1)

        # Test the lower range.
        version2 = Version.objects.create(id=1, addon=self.addon,
                                          version='0.5')
        eq_(IncompatibleVersions.objects.filter(version=version2).count(), 1)
        eq_(IncompatibleVersions.objects.count(), 2)

        # Test delete signals.
        version1.delete()
        eq_(IncompatibleVersions.objects.count(), 1)

        version2.delete()
        eq_(IncompatibleVersions.objects.count(), 0)

    def test_signals_max(self):
        eq_(IncompatibleVersions.objects.count(), 0)

        c = CompatOverride.objects.create(guid='r@b')
        CompatOverrideRange.objects.create(compat=c, app=self.app,
                                           min_version='1.0',
                                           max_version='*')

        # Test the min_version matched.
        version1 = Version.objects.create(addon=self.addon, version='1.0')
        eq_(IncompatibleVersions.objects.filter(version=version1).count(), 1)
        eq_(IncompatibleVersions.objects.count(), 1)

        # Test the upper range.
        version2 = Version.objects.create(addon=self.addon, version='99.0')
        eq_(IncompatibleVersions.objects.filter(version=version2).count(), 1)
        eq_(IncompatibleVersions.objects.count(), 2)

        # Test delete signals.
        version1.delete()
        eq_(IncompatibleVersions.objects.count(), 1)

        version2.delete()
        eq_(IncompatibleVersions.objects.count(), 0)


class TestQueue(amo.tests.TestCase):

    def test_in_queue(self):
        addon = Addon.objects.create(guid='f', type=amo.ADDON_EXTENSION)
        assert not addon.in_escalation_queue()
        EscalationQueue.objects.create(addon=addon)
        assert addon.in_escalation_queue()
