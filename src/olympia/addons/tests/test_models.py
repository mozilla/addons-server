# -*- coding: utf-8 -*-
import json
import os
import time
from datetime import datetime, timedelta

from django import forms
from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage as storage
from django.db import IntegrityError
from django.utils import translation

import jingo
from mock import Mock, patch

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo import set_user
from olympia.amo.helpers import absolutify, user_media_url
from olympia.addons.models import (
    Addon, AddonCategory, AddonDependency, AddonFeatureCompatibility,
    AddonUser, AppSupport, BlacklistedGuid, BlacklistedSlug, Category, Charity,
    CompatOverride, CompatOverrideRange, FrozenAddon, IncompatibleVersions,
    Persona, Preview, track_addon_status_change)
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.devhub.models import ActivityLog, AddonLog, RssKey, SubmitStep
from olympia.editors.models import EscalationQueue
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.reviews.models import Review, ReviewFlag
from olympia.translations.models import Translation, TranslationSequence
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, Version
from olympia.versions.compare import version_int


class TestCleanSlug(TestCase):

    def test_clean_slug_new_object(self):
        # Make sure there's at least an addon with the "addon" slug, subsequent
        # ones should be "addon-1", "addon-2" ...
        a = Addon.objects.create()
        assert a.slug == "addon"

        # Start with a first clash. This should give us "addon-1".
        # We're not saving yet, we're testing the slug creation without an id.
        b = Addon()
        b.clean_slug()
        assert b.slug == 'addon1'
        # Now save the instance to the database for future clashes.
        b.save()

        # Test on another object without an id.
        c = Addon()
        c.clean_slug()
        assert c.slug == 'addon2'

        # Even if an addon is deleted, don't clash with its slug.
        c.status = amo.STATUS_DELETED
        # Now save the instance to the database for future clashes.
        c.save()

        # And yet another object without an id. Make sure we're not trying to
        # assign the 'addon-2' slug from the deleted addon.
        d = Addon()
        d.clean_slug()
        assert d.slug == 'addon3'

    def test_clean_slug_with_id(self):
        # Create an addon and save it to have an id.
        a = Addon.objects.create()
        # Start over: don't use the name nor the id to generate the slug.
        a.slug = a.name = ""
        a.clean_slug()
        # Slugs created from an id are of the form "id~", eg "123~" to avoid
        # clashing with URLs.
        assert a.slug == "%s~" % a.id

        # And again, this time make it clash.
        b = Addon.objects.create()
        # Set a's slug to be what should be created for b from its id.
        a.slug = "%s~" % b.id
        a.save()

        # Now start over for b.
        b.slug = b.name = ""
        b.clean_slug()
        assert b.slug == "%s~1" % b.id

    def test_clean_slug_with_name(self):
        # Make sure there's at least an addon with the "fooname" slug,
        # subsequent ones should be "fooname-1", "fooname-2" ...
        a = Addon.objects.create(name="fooname")
        assert a.slug == "fooname"

        b = Addon(name="fooname")
        b.clean_slug()
        assert b.slug == "fooname1"

    def test_clean_slug_with_slug(self):
        # Make sure there's at least an addon with the "fooslug" slug,
        # subsequent ones should be "fooslug-1", "fooslug-2" ...
        a = Addon.objects.create(name="fooslug")
        assert a.slug == "fooslug"

        b = Addon(name="fooslug")
        b.clean_slug()
        assert b.slug == "fooslug1"

    def test_clean_slug_blacklisted_slug(self):
        blacklisted_slug = 'fooblacklisted'
        BlacklistedSlug.objects.create(name=blacklisted_slug)

        a = Addon(slug=blacklisted_slug)
        a.clean_slug()
        # Blacklisted slugs (like "activate" or IDs) have a "~" appended to
        # avoid clashing with URLs.
        assert a.slug == "%s~" % blacklisted_slug
        # Now save the instance to the database for future clashes.
        a.save()

        b = Addon(slug=blacklisted_slug)
        b.clean_slug()
        assert b.slug == "%s~1" % blacklisted_slug

    def test_clean_slug_blacklisted_slug_long_slug(self):
        long_slug = "this_is_a_very_long_slug_that_is_longer_than_thirty_chars"
        BlacklistedSlug.objects.create(name=long_slug[:30])

        # If there's no clashing slug, just append a "~".
        a = Addon.objects.create(slug=long_slug[:30])
        assert a.slug == "%s~" % long_slug[:29]

        # If there's a clash, use the standard clash resolution.
        a = Addon.objects.create(slug=long_slug[:30])
        assert a.slug == "%s1" % long_slug[:28]

    def test_clean_slug_long_slug(self):
        long_slug = "this_is_a_very_long_slug_that_is_longer_than_thirty_chars"

        # If there's no clashing slug, don't over-shorten it.
        a = Addon.objects.create(slug=long_slug)
        assert a.slug == long_slug[:30]

        # Now that there is a clash, test the clash resolution.
        b = Addon(slug=long_slug)
        b.clean_slug()
        assert b.slug == "%s1" % long_slug[:28]

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

    def test_clean_slug_ends_with_dash(self):
        """Addon name ending with a dash should still work: See bug 1206063."""
        a = Addon.objects.create(name='ends with dash -')
        assert a.slug == 'ends-with-dash-'
        assert a.slug == amo.utils.slugify(a.slug)

        b = Addon.objects.create(name='ends with dash -')
        assert b.slug == 'ends-with-dash-1'
        assert b.slug == amo.utils.slugify(b.slug)


class TestAddonManager(TestCase):
    fixtures = ['base/appversion', 'base/users',
                'base/addon_3615', 'addons/featured', 'addons/test_manager',
                'base/collections', 'base/featured',
                'bandwagon/featured_collections', 'base/addon_5299_gcal']

    def setUp(self):
        super(TestAddonManager, self).setUp()
        set_user(None)
        self.addon = Addon.objects.get(pk=3615)

    def change_addon_visibility(self, deleted=False, listed=True):
        self.addon.update(
            status=amo.STATUS_DELETED if deleted else amo.STATUS_PUBLIC,
            is_listed=listed)

    def test_managers_public(self):
        assert self.addon in Addon.objects.all()
        assert self.addon in Addon.with_unlisted.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_unlisted(self):
        self.change_addon_visibility(listed=False)
        assert self.addon not in Addon.objects.all()
        assert self.addon in Addon.with_unlisted.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_unlisted_deleted(self):
        self.change_addon_visibility(deleted=True, listed=False)
        assert self.addon not in Addon.objects.all()
        assert self.addon not in Addon.with_unlisted.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_deleted(self):
        self.change_addon_visibility(deleted=True, listed=True)
        assert self.addon not in Addon.objects.all()
        assert self.addon not in Addon.with_unlisted.all()
        assert self.addon in Addon.unfiltered.all()

    def test_featured(self):
        assert Addon.objects.featured(amo.FIREFOX).count() == 3

    def test_listed(self):
        # We need this for the fixtures, but it messes up the tests.
        self.addon.update(disabled_by_user=True)
        # Now continue as normal.
        Addon.objects.filter(id=5299).update(disabled_by_user=True)
        q = Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC)
        assert len(q.all()) == 4

        # Pick one of the listed addons.
        addon = Addon.objects.get(pk=2464)
        assert addon in q.all()

        # Disabling hides it.
        addon.disabled_by_user = True
        addon.save()

        # Should be 3 now, since the one is now disabled.
        assert q.count() == 3

        # If we search for public or unreviewed we find it.
        addon.disabled_by_user = False
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        assert q.count() == 3
        assert Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC,
                                    amo.STATUS_UNREVIEWED).count() == 4

        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        assert q.count() == 3

    def test_public(self):
        public = Addon.objects.public()
        for a in public:
            assert a.id != 3  # 'public() must not return unreviewed add-ons'

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
        assert Addon.objects.valid_and_disabled_and_pending().count() == before

    def test_valid_disabled_by_admin(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        addon = Addon.objects.get(pk=5299)
        addon.update(status=amo.STATUS_DISABLED)
        assert Addon.objects.valid_and_disabled_and_pending().count() == before

    def test_invalid_deleted(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        addon = Addon.objects.get(pk=5299)
        addon.update(status=amo.STATUS_DELETED)
        assert Addon.objects.valid_and_disabled_and_pending().count() == (
            before - 1)

    def test_valid_disabled_pending(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()
        amo.tests.addon_factory(status=amo.STATUS_PENDING)
        assert Addon.objects.valid_and_disabled_and_pending().count() == (
            before + 1)

    def test_valid_disabled_version(self):
        before = Addon.objects.valid_and_disabled_and_pending().count()

        # Add-on, no version. Doesn't count.
        addon = amo.tests.addon_factory()
        addon.update(_current_version=None, _signal=False)
        assert Addon.objects.valid_and_disabled_and_pending().count() == before

        # Theme, no version. Counts.
        addon = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        addon.update(_current_version=None, _signal=False)
        assert Addon.objects.valid_and_disabled_and_pending().count() == (
            before + 1)

    def test_new_featured(self):
        f = Addon.objects.featured(amo.FIREFOX)
        assert f.count() == 3
        assert sorted(x.id for x in f) == (
            [2464, 7661, 15679])
        f = Addon.objects.featured(amo.THUNDERBIRD)
        assert not f.exists()

    def test_filter_for_many_to_many(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        collection = self.addon.collections.first()
        assert collection.addons.get() == self.addon

        # Addon shouldn't be listed in collection.addons if it's deleted or
        # unlisted.

        # Unlisted.
        self.addon.update(is_listed=False)
        collection = Collection.objects.get(pk=collection.pk)
        assert collection.addons.count() == 0

        # Deleted and unlisted.
        self.addon.update(status=amo.STATUS_DELETED)
        collection = Collection.objects.get(pk=collection.pk)
        assert collection.addons.count() == 0

        # Only deleted.
        self.addon.update(is_listed=True)
        collection = Collection.objects.get(pk=collection.pk)
        assert collection.addons.count() == 0

    def test_no_filter_for_relations(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        version = self.addon.versions.first()
        assert version.addon == self.addon

        # Deleted or unlisted, version.addon should still work.

        # Unlisted.
        self.addon.update(is_listed=False)
        version = Version.objects.get(pk=version.pk)  # Reload from db.
        assert version.addon == self.addon

        # Deleted and unlisted.
        self.addon.update(status=amo.STATUS_DELETED)
        version = Version.objects.get(pk=version.pk)  # Reload from db.
        assert version.addon == self.addon

        # Only deleted.
        self.addon.update(is_listed=True)
        version = Version.objects.get(pk=version.pk)  # Reload from db.
        assert version.addon == self.addon


class TestAddonModels(TestCase):
    fixtures = ['base/appversion',
                'base/collections',
                'base/featured',
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
        super(TestAddonModels, self).setUp()
        TranslationSequence.objects.create(id=99243)
        # TODO(andym): use Mock appropriately here.
        self.old_version = amo.FIREFOX.latest_version
        amo.FIREFOX.latest_version = '3.6.15'

    def tearDown(self):
        amo.FIREFOX.latest_version = self.old_version
        super(TestAddonModels, self).tearDown()

    def test_current_version(self):
        """
        Tests that we get the current (latest public) version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        assert a.current_version.id == 81551

    def test_current_version_listed(self):
        a = Addon.objects.get(pk=3723)
        assert a.current_version.id == 89774

    def test_current_version_listed_no_version(self):
        Addon.objects.filter(pk=3723).update(_current_version=None)
        Version.objects.filter(addon=3723).delete()
        a = Addon.objects.get(pk=3723)
        assert a.current_version is None

    def test_latest_version(self):
        """
        Tests that we get the latest version of an addon.
        """
        a = Addon.objects.get(pk=3615)
        assert a.latest_version.id == (
            Version.objects.filter(addon=a).latest().id)

    def test_latest_version_no_version(self):
        Addon.objects.filter(pk=3723).update(_current_version=None)
        Version.objects.filter(addon=3723).delete()
        a = Addon.objects.get(pk=3723)
        assert a.latest_version is None

    def test_latest_version_ignore_beta(self):
        a = Addon.objects.get(pk=3615)

        v1 = Version.objects.create(addon=a, version='1.0')
        File.objects.create(version=v1)
        assert a.latest_version.id == v1.id

        v2 = Version.objects.create(addon=a, version='2.0beta')
        File.objects.create(version=v2, status=amo.STATUS_BETA)
        v2.save()
        assert a.latest_version.id == v1.id  # Still should be v1

    def test_latest_version_ignore_disabled(self):
        a = Addon.objects.get(pk=3615)

        v1 = Version.objects.create(addon=a, version='1.0')
        File.objects.create(version=v1)
        assert a.latest_version.id == v1.id

        v2 = Version.objects.create(addon=a, version='2.0')
        File.objects.create(version=v2, status=amo.STATUS_DISABLED)
        v2.save()
        assert a.latest_version.id == v1.id  # Still should be v1

    def test_current_version_unsaved(self):
        a = Addon()
        a._current_version = Version()
        assert a.current_version is None

    def test_latest_version_unsaved(self):
        a = Addon()
        a._latest_version = Version()
        assert a.latest_version is None

    def test_current_beta_version(self):
        a = Addon.objects.get(pk=5299)
        assert a.current_beta_version.id == 50000

    def _create_new_version(self, addon, status):
        av = addon.current_version.apps.all()[0]

        v = Version.objects.create(addon=addon, version='99')
        File.objects.create(status=status, version=v)

        ApplicationsVersions.objects.create(application=amo.FIREFOX.id,
                                            version=v, min=av.min, max=av.max)
        return v

    def test_compatible_version(self):
        a = Addon.objects.get(pk=3615)
        assert a.status == amo.STATUS_PUBLIC

        v = self._create_new_version(addon=a, status=amo.STATUS_PUBLIC)

        assert a.compatible_version(amo.FIREFOX.id) == v

    def test_compatible_version_status(self):
        """
        Tests that `compatible_version()` won't return a lited version for a
        fully-reviewed add-on.
        """
        a = Addon.objects.get(pk=3615)
        assert a.status == amo.STATUS_PUBLIC

        v = self._create_new_version(addon=a, status=amo.STATUS_LITE)

        assert a.current_version != v
        assert a.compatible_version(amo.FIREFOX.id) == a.current_version

    def test_transformer(self):
        addon = Addon.objects.get(pk=3615)
        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            addon._current_version
            addon.latest_version

    def _delete(self, addon_id):
        """Test deleting add-ons."""
        set_user(UserProfile.objects.last())
        addon_count = Addon.unfiltered.count()
        addon = Addon.objects.get(pk=addon_id)
        guid = addon.guid
        addon.delete('bye')
        assert addon_count == Addon.unfiltered.count()  # Soft deletion.
        assert addon.status == amo.STATUS_DELETED
        assert addon.slug is None
        assert addon.current_version is None
        assert addon.guid == guid  # We don't clear it anymore.
        deleted_count = Addon.unfiltered.filter(
            status=amo.STATUS_DELETED).count()
        assert len(mail.outbox) == deleted_count
        log = AddonLog.objects.order_by('-id').first().activity_log
        assert log.action == amo.LOG.DELETE_ADDON.id
        assert log.to_string() == (
            "Addon id {0} with GUID {1} has been deleted".format(addon_id,
                                                                 guid))

    def test_delete(self):
        addon = Addon.unfiltered.get(pk=3615)
        addon.name = u'é'  # Make sure we don't have encoding issues.
        addon.save()
        self._delete(3615)

        # Delete another add-on, and make sure we don't have integrity errors
        # with unique constraints on fields that got nullified.
        self._delete(5299)

    def test_delete_persona(self):
        addon = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        assert addon.guid is None  # Personas don't have GUIDs.
        self._delete(addon.pk)

    def _delete_url(self):
        """Test deleting addon has URL in the email."""
        a = Addon.objects.get(pk=4594)
        url = a.get_url_path()
        a.delete('bye')
        assert absolutify(url) in mail.outbox[0].body

    def test_delete_url(self):
        count = Addon.unfiltered.count()
        self._delete_url()
        assert count == Addon.unfiltered.count()

    def test_delete_reason(self):
        """Test deleting with a reason gives the reason in the mail."""
        reason = u'trêason'
        a = Addon.objects.get(pk=3615)
        a.name = u'é'
        assert len(mail.outbox) == 0
        a.delete(msg='bye', reason=reason)
        assert len(mail.outbox) == 1
        assert reason in mail.outbox[0].body

    def test_delete_incomplete_no_versions(self):
        """Test deleting incomplete add-ons."""
        count = Addon.unfiltered.count()
        a = Addon.objects.get(pk=3615)
        a.latest_version.delete(hard=True)
        a.status = 0
        a.save()
        a.delete(None)
        assert len(mail.outbox) == 0
        assert Addon.unfiltered.count() == (count - 1)

    def test_delete_incomplete_with_versions(self):
        """Test deleting incomplete add-ons."""
        count = Addon.unfiltered.count()
        a = Addon.objects.get(pk=3615)
        a.status = 0
        a.save()
        a.delete('oh looky here')
        assert len(mail.outbox) == 1
        assert count == Addon.unfiltered.count()

    def test_delete_searchengine(self):
        """
        Test deleting searchengines (which have no guids) should not barf up
        the deletion machine.
        """
        a = Addon.objects.get(pk=4594)
        a.delete('bye')
        assert len(mail.outbox) == 1

    def test_incompatible_latest_apps(self):
        a = Addon.objects.get(pk=3615)
        assert a.incompatible_latest_apps() == []

        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.get(pk=97)  # Firefox 2.0
        av.save()

        a = Addon.objects.get(pk=3615)
        assert a.incompatible_latest_apps() == [amo.FIREFOX]

        # Check a search engine addon.
        a = Addon.objects.get(pk=4594)
        assert a.incompatible_latest_apps() == []

    def test_incompatible_asterix(self):
        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.create(application=amo.FIREFOX.id,
                                           version_int=version_int('5.*'),
                                           version='5.*')
        av.save()
        a = Addon.objects.get(pk=3615)
        assert a.incompatible_latest_apps() == []

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
        assert a.icon_url.endswith(default)
        assert a.get_icon_url(32).endswith(default)
        assert a.get_icon_url(32, use_default=True).endswith(default)
        assert a.get_icon_url(32, use_default=False) is None

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

    def test_is_reviewed(self):
        # Public add-on.
        addon = Addon.objects.get(pk=3615)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.is_reviewed()

        # Public, disabled add-on.
        addon.disabled_by_user = True
        assert addon.is_reviewed()  # It's still considered "reviewed".

        # Preliminarily Reviewed.
        addon.status = amo.STATUS_LITE
        assert addon.is_reviewed()

        # Preliminarily Reviewed and Awaiting Full Review.
        addon.status = amo.STATUS_LITE_AND_NOMINATED
        assert addon.is_reviewed()

        # Unreviewed add-on.
        addon.status = amo.STATUS_UNREVIEWED
        assert not addon.is_reviewed()

    def test_is_no_restart(self):
        a = Addon.objects.get(pk=3615)
        f = a.current_version.all_files[0]
        assert not f.no_restart
        assert not a.is_no_restart()

        f.update(no_restart=True)
        assert Addon.objects.get(pk=3615).is_no_restart()

        a.versions.all().delete()
        a._current_version = None
        assert not a.is_no_restart()

    def test_is_featured(self):
        """Test if an add-on is globally featured"""
        a = Addon.objects.get(pk=1003)
        assert a.is_featured(amo.FIREFOX, 'en-US'), (
            'globally featured add-on not recognized')

    def test_has_full_profile(self):
        """Test if an add-on's developer profile is complete (public)."""
        def addon():
            return Addon.objects.get(pk=3615)

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
        def addon():
            return Addon.objects.get(pk=3615)

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
        def addon():
            return Addon.objects.get(pk=3615)

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

        assert self.newlines_helper(before) == after

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

        assert self.newlines_helper(before) == after

    def test_newlines_ul_tight(self):
        before = ("There should be one nl between this and the ul.\n"
                  "<ul><li>test</li><li>test</li></ul>\n"
                  "There should be no nl's above this line.")

        after = ("There should be one nl between this and the ul.\n"
                 "<ul><li>test</li><li>test</li></ul>"
                 "There should be no nl's above this line.")

        assert self.newlines_helper(before) == after

    def test_newlines_ul_loose(self):
        before = ("There should be two nl's between this and the ul.\n\n"
                  "<ul><li>test</li><li>test</li></ul>\n\n"
                  "There should be one nl above this line.")

        after = ("There should be two nl's between this and the ul.\n\n"
                 "<ul><li>test</li><li>test</li></ul>\n"
                 "There should be one nl above this line.")

        assert self.newlines_helper(before) == after

    def test_newlines_blockquote_tight(self):
        before = ("There should be one nl below this.\n"
                  "<blockquote>Hi</blockquote>\n"
                  "There should be no nl's above this.")

        after = ("There should be one nl below this.\n"
                 "<blockquote>Hi</blockquote>"
                 "There should be no nl's above this.")

        assert self.newlines_helper(before) == after

    def test_newlines_blockquote_loose(self):
        before = ("There should be two nls below this.\n\n"
                  "<blockquote>Hi</blockquote>\n\n"
                  "There should be one nl above this.")

        after = ("There should be two nls below this.\n\n"
                 "<blockquote>Hi</blockquote>\n"
                 "There should be one nl above this.")

        assert self.newlines_helper(before) == after

    def test_newlines_inline(self):
        before = ("If we end a paragraph w/ a <b>non-block-level tag</b>\n\n"
                  "<b>The newlines</b> should be kept")

        after = before  # Should stay the same

        assert self.newlines_helper(before) == after

    def test_newlines_code_inline(self):
        before = ("Code tags aren't blocks.\n\n"
                  "<code>alert(test);</code>\n\n"
                  "See?")

        after = before  # Should stay the same

        assert self.newlines_helper(before) == after

    def test_newlines_li_newlines(self):
        before = ("<ul><li>\nxx</li></ul>")
        after = ("<ul><li>xx</li></ul>")
        assert self.newlines_helper(before) == after

        before = ("<ul><li>xx\n</li></ul>")
        after = ("<ul><li>xx</li></ul>")
        assert self.newlines_helper(before) == after

        before = ("<ul><li>xx\nxx</li></ul>")
        after = ("<ul><li>xx\nxx</li></ul>")
        assert self.newlines_helper(before) == after

        before = ("<ul><li></li></ul>")
        after = ("<ul><li></li></ul>")
        assert self.newlines_helper(before) == after

        # All together now
        before = ("<ul><li>\nxx</li> <li>xx\n</li> <li>xx\nxx</li> "
                  "<li></li>\n</ul>")

        after = ("<ul><li>xx</li> <li>xx</li> <li>xx\nxx</li> "
                 "<li></li></ul>")

        assert self.newlines_helper(before) == after

    def test_newlines_empty_tag(self):
        before = ("This is a <b></b> test!")
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_empty_tag_nested(self):
        before = ("This is a <b><i></i></b> test!")
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_empty_tag_block_nested(self):
        b = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>\ntest.")
        a = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>test.")

        assert self.newlines_helper(b) == a

    def test_newlines_empty_tag_block_nested_spaced(self):
        before = ("Test.\n\n<blockquote>\n\n<ul>\n\n<li>"
                  "</li>\n\n</ul>\n\n</blockquote>\ntest.")
        after = ("Test.\n\n<blockquote><ul><li></li></ul></blockquote>test.")

        assert self.newlines_helper(before) == after

    def test_newlines_li_newlines_inline(self):
        before = ("<ul><li>\n<b>test\ntest\n\ntest</b>\n</li>"
                  "<li>Test <b>test</b> test.</li></ul>")

        after = ("<ul><li><b>test\ntest\n\ntest</b></li>"
                 "<li>Test <b>test</b> test.</li></ul>")

        assert self.newlines_helper(before) == after

    def test_newlines_li_all_inline(self):
        before = ("Test with <b>no newlines</b> and <code>block level "
                  "stuff</code> to see what happens.")

        after = before  # Should stay the same

        assert self.newlines_helper(before) == after

    def test_newlines_spaced_blocks(self):
        before = ("<blockquote>\n\n<ul>\n\n<li>\n\ntest\n\n</li>\n\n"
                  "</ul>\n\n</blockquote>")

        after = "<blockquote><ul><li>test</li></ul></blockquote>"

        assert self.newlines_helper(before) == after

    def test_newlines_spaced_inline(self):
        before = "Line.\n\n<b>\nThis line is bold.\n</b>\n\nThis isn't."
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_nested_inline(self):
        before = "<b>\nThis line is bold.\n\n<i>This is also italic</i></b>"
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_xss_script(self):
        before = "<script>\n\nalert('test');\n</script>"
        after = "&lt;script&gt;\n\nalert('test');\n&lt;/script&gt;"

        assert self.newlines_helper(before) == after

    def test_newlines_xss_inline(self):
        before = "<b onclick=\"alert('test');\">test</b>"
        after = "<b>test</b>"

        assert self.newlines_helper(before) == after

    @patch('olympia.amo.helpers.urlresolvers.get_outgoing_url')
    def test_newlines_attribute_link_doublequote(self, mock_get_outgoing_url):
        mock_get_outgoing_url.return_value = 'http://google.com'
        before = '<a href="http://google.com">test</a>'

        parsed = self.newlines_helper(before)

        assert 'rel="nofollow"' in parsed

    def test_newlines_attribute_singlequote(self):
        before = "<abbr title='laugh out loud'>lol</abbr>"
        after = '<abbr title="laugh out loud">lol</abbr>'

        assert self.newlines_helper(before) == after

    def test_newlines_attribute_doublequote(self):
        before = '<abbr title="laugh out loud">lol</abbr>'
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_attribute_nestedquotes_doublesingle(self):
        before = '<abbr title="laugh \'out\' loud">lol</abbr>'
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_attribute_nestedquotes_singledouble(self):
        before = '<abbr title=\'laugh "out" loud\'>lol</abbr>'
        after = before

        assert self.newlines_helper(before) == after

    def test_newlines_unclosed_b(self):
        before = ("<b>test")
        after = ("<b>test</b>")

        assert self.newlines_helper(before) == after

    def test_newlines_unclosed_b_wrapped(self):
        before = ("This is a <b>test")
        after = ("This is a <b>test</b>")

        assert self.newlines_helper(before) == after

    def test_newlines_unclosed_li(self):
        before = ("<ul><li>test</ul>")
        after = ("<ul><li>test</li></ul>")

        assert self.newlines_helper(before) == after

    def test_newlines_malformed_faketag(self):
        before = "<madonna"
        after = ""

        assert self.newlines_helper(before) == after

    def test_newlines_correct_faketag(self):
        before = "<madonna>"
        after = "&lt;madonna&gt;"

        assert self.newlines_helper(before) == after

    def test_newlines_malformed_tag(self):
        before = "<strong"
        after = ""

        assert self.newlines_helper(before) == after

    def test_newlines_malformed_faketag_surrounded(self):
        before = "This is a <test of bleach"
        after = 'This is a'
        assert self.newlines_helper(before) == after

    def test_newlines_malformed_tag_surrounded(self):
        before = "This is a <strong of bleach"
        after = "This is a"
        assert self.newlines_helper(before) == after

    def test_newlines_less_than(self):
        before = "3 < 5"
        after = "3 &lt; 5"

        assert self.newlines_helper(before) == after

    def test_newlines_less_than_tight(self):
        before = "abc 3<5 def"
        after = "abc 3&lt;5 def"

        assert self.newlines_helper(before) == after

    def test_app_numeric_slug(self):
        cat = Category.objects.get(id=22)
        cat.slug = 123
        with self.assertRaises(ValidationError):
            cat.full_clean()

    def test_app_categories(self):
        def addon():
            return Addon.objects.get(pk=3615)

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
        assert cats == [c22, c23, c24]
        for cat in cats:
            assert cat.application == amo.FIREFOX.id

        cats = [c24, c23, c22]
        app_cats = [(amo.FIREFOX, cats)]
        assert addon().app_categories == app_cats

        c = Category(application=amo.THUNDERBIRD.id, name='XXX',
                     type=addon().type, count=1, weight=1)
        c.save()
        AddonCategory.objects.create(addon=addon(), category=c)
        c24.save()  # Clear the app_categories cache.
        app_cats += [(amo.THUNDERBIRD, [c])]
        assert addon().app_categories == app_cats

    def test_app_categories_sunbird(self):
        def get_addon():
            return Addon.objects.get(pk=3615)

        addon = get_addon()

        # This add-on is already associated with three Firefox categories.
        cats = sorted(addon.categories.all(), key=lambda x: x.name)
        assert addon.app_categories == [(amo.FIREFOX, cats)]

        # Associate this add-on with a Sunbird category.
        c2 = Category.objects.create(application=amo.SUNBIRD.id,
                                     type=amo.ADDON_EXTENSION, name='Sunny D')
        AddonCategory.objects.create(addon=addon, category=c2)

        # Sunbird category should be excluded.
        assert get_addon().app_categories == [(amo.FIREFOX, cats)]

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

    @patch('olympia.addons.models.Addon.current_beta_version')
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
        assert entries[0].action == amo.LOG.CHANGE_STATUS.id

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
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.is_disabled

    def test_no_change_disabled(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        addon.update(status=amo.STATUS_DISABLED)
        version.save()
        assert addon.status == amo.STATUS_DISABLED
        assert addon.is_disabled

    def test_no_change_deleted(self):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        addon.update(status=amo.STATUS_DELETED)
        version.save()
        assert addon.status == amo.STATUS_DELETED
        assert addon.is_deleted

    def test_can_alter_in_prelim(self):
        addon, version = self.setup_files(amo.STATUS_LITE)
        addon.update(status=amo.STATUS_LITE)
        version.save()
        assert addon.status == amo.STATUS_LITE

    def test_removing_public(self):
        addon, version = self.setup_files(amo.STATUS_UNREVIEWED)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        assert addon.status == amo.STATUS_UNREVIEWED

    def test_removing_public_with_prelim(self):
        addon, version = self.setup_files(amo.STATUS_LITE)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        assert addon.status == amo.STATUS_LITE

    def test_can_request_review_no_files(self):
        addon = Addon.objects.get(pk=3615)
        addon.versions.all()[0].files.all().delete()
        assert addon.can_request_review() == ()

    def test_can_request_review_rejected(self):
        addon = Addon.objects.get(pk=3615)
        addon.latest_version.files.update(status=amo.STATUS_DISABLED)
        assert addon.can_request_review() == ()

    def check(self, status, exp, kw={}):
        addon = Addon.objects.get(pk=3615)
        changes = {'status': status, 'disabled_by_user': False}
        changes.update(**kw)
        addon.update(**changes)
        assert addon.can_request_review() == exp

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

    def test_none_homepage(self):
        # There was an odd error when a translation was set to None.
        Addon.objects.create(homepage=None, type=amo.ADDON_EXTENSION)

    def test_slug_isdigit(self):
        a = Addon.objects.create(type=1, name='xx', slug='123')
        assert a.slug == '123~'

        a.slug = '44'
        a.save()
        assert a.slug == '44~'

    def test_slug_isblacklisted(self):
        # When an addon is uploaded, it doesn't use the form validation,
        # so we'll just mangle the slug if its blacklisted.
        a = Addon.objects.create(type=1, name='xx', slug='validate')
        assert a.slug == 'validate~'

        a.slug = 'validate'
        a.save()
        assert a.slug == 'validate~'

    def delete(self):
        addon = Addon.objects.get(id=3615)
        assert len(mail.outbox) == 0
        addon.delete('so long and thanks for all the fish')
        assert len(mail.outbox) == 1

    def test_delete_to(self):
        self.delete()
        assert mail.outbox[0].to == [settings.FLIGTAR]

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

    def test_delete_mail_not_localized(self):
        """Don't localize the email sent to the admins using the user's
        locale."""
        with self.activate('pl'):
            self.delete()
        admin_mail = mail.outbox[0]
        # Make sure the type (EXTENSION) isn't localized.
        assert 'Deleting EXTENSION a3615 (3615)' in admin_mail.subject
        assert 'The following EXTENSION was deleted' in admin_mail.body

    def test_view_source(self):
        # view_source should default to True.
        a = Addon.objects.create(type=1)
        assert a.view_source

    @patch('olympia.files.models.File.hide_disabled_file')
    def test_admin_disabled_file_hidden(self, hide_mock):
        a = Addon.objects.get(id=3615)
        a.status = amo.STATUS_PUBLIC
        a.save()
        assert not hide_mock.called

        a.status = amo.STATUS_DISABLED
        a.save()
        assert hide_mock.called

    @patch('olympia.files.models.File.hide_disabled_file')
    def test_user_disabled_file_hidden(self, hide_mock):
        a = Addon.objects.get(id=3615)
        a.disabled_by_user = False
        a.save()
        assert not hide_mock.called

        a.disabled_by_user = True
        a.save()
        assert hide_mock.called

    def test_category_transform(self):
        addon = Addon.objects.get(id=3615)
        cats = addon.categories.filter(application=amo.FIREFOX.id)
        names = [c.name for c in cats]
        assert addon.get_category(amo.FIREFOX.id).name in names

    def test_binary_property(self):
        addon = Addon.objects.get(id=3615)
        file = addon.current_version.files.all()[0]
        file.update(binary=True)
        assert addon.binary

    def test_binary_components_property(self):
        addon = Addon.objects.get(id=3615)
        file = addon.current_version.files.all()[0]
        file.update(binary_components=True)
        assert addon.binary_components

    def test_is_incomplete(self):
        addon = Addon.objects.get(pk=3615)
        SubmitStep.objects.create(addon=addon, step=6)
        assert addon.is_incomplete()

    def test_unlisted_is_incomplete(self):
        addon = Addon.objects.get(pk=3615)
        SubmitStep.objects.create(addon=addon, step=2)
        assert addon.is_incomplete()


class TestAddonNomination(TestCase):
    fixtures = ['base/addon_3615']

    def test_set_nomination(self):
        a = Addon.objects.get(id=3615)
        for status in amo.UNDER_REVIEW_STATUSES:
            a.update(status=amo.STATUS_NULL)
            a.versions.latest().update(nomination=None)
            a.update(status=status)
            assert a.versions.latest().nomination

    def test_new_version_inherits_nomination(self):
        a = Addon.objects.get(id=3615)
        ver = 10
        for status in amo.UNDER_REVIEW_STATUSES:
            a.update(status=status)
            old_ver = a.versions.latest()
            v = Version.objects.create(addon=a, version=str(ver))
            assert v.nomination == old_ver.nomination
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
        assert v.nomination is None

    def test_lone_version_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        Version.objects.all().delete()
        v = Version.objects.create(addon=a, version='1.0')
        assert v.nomination is None

    def test_reviewed_addon_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        ver = 10
        for st in (amo.STATUS_PUBLIC, amo.STATUS_BETA, amo.STATUS_NULL):
            a.update(status=st)
            v = Version.objects.create(addon=a, version=str(ver))
            assert v.nomination is None
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
        assert addon.versions.latest().nomination.date() == earlier.date()

    def setup_nomination(self, status=amo.STATUS_UNREVIEWED):
        addon = Addon.objects.create()
        version = Version.objects.create(addon=addon)
        File.objects.create(status=status, version=version)
        # Cheating date to make sure we don't have a date on the same second
        # the code we test is running.
        past = self.days_ago(1)
        version.update(nomination=past, created=past, modified=past)
        addon.update(status=status)
        nomination = addon.versions.latest().nomination
        assert nomination
        return addon, nomination

    def test_new_version_of_under_review_addon_does_not_reset_nomination(self):
        addon, nomination = self.setup_nomination()
        version = Version.objects.create(addon=addon, version='0.2')
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        assert addon.versions.latest().nomination == nomination

    def test_nomination_not_reset_if_changing_addon_status(self):
        """
        When under review, switching status should not reset nomination.
        """
        addon, nomination = self.setup_nomination()
        # Now switch to a full review.
        addon.update(status=amo.STATUS_NOMINATED)
        assert addon.versions.latest().nomination == nomination
        # Then again to a preliminary.
        addon.update(status=amo.STATUS_UNREVIEWED)
        assert addon.versions.latest().nomination == nomination
        # Finally back to a reviewed status.
        addon.update(status=amo.STATUS_PUBLIC)
        assert addon.versions.latest().nomination == nomination

    def test_nomination_not_reset_if_adding_new_versions_and_files(self):
        """
        When under review, adding new versions and files should not
        reset nomination.
        """
        addon, nomination = self.setup_nomination()
        # Switching it to a public status.
        version = Version.objects.create(addon=addon, version="0.1")
        File.objects.create(status=amo.STATUS_PUBLIC, version=version)
        assert addon.versions.latest().nomination == nomination
        # Adding a new unreviewed version.
        version = Version.objects.create(addon=addon, version="0.2")
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        assert addon.versions.latest().nomination == nomination
        # Adding a new unreviewed version.
        version = Version.objects.create(addon=addon, version="0.3")
        File.objects.create(status=amo.STATUS_NOMINATED, version=version)
        assert addon.versions.latest().nomination == nomination

    def check_nomination_reset_with_new_version(self, addon, nomination):
        version = Version.objects.create(addon=addon, version="0.2")
        assert version.nomination is None
        File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        assert addon.versions.latest().nomination != nomination

    def test_new_version_of_public_addon_should_reset_nomination(self):
        addon, nomination = self.setup_nomination(status=amo.STATUS_LITE)
        # Update again, but without a new version.
        addon.update(status=amo.STATUS_LITE)
        # Check that nomination has been reset.
        assert addon.versions.latest().nomination == nomination
        # Now create a new version with an attached file, and update status.
        self.check_nomination_reset_with_new_version(addon, nomination)

    def test_new_version_of_fully_reviewed_addon_should_reset_nomination(self):
        addon, nomination = self.setup_nomination(status=amo.STATUS_PUBLIC)
        # Now create a new version with an attached file, and update status.
        self.check_nomination_reset_with_new_version(addon, nomination)


class TestAddonDelete(TestCase):

    def test_cascades(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

        AddonCategory.objects.create(
            addon=addon,
            category=Category.objects.create(type=amo.ADDON_EXTENSION))
        AddonDependency.objects.create(
            addon=addon, dependent_addon=addon)
        AddonUser.objects.create(
            addon=addon, user=UserProfile.objects.create())
        AppSupport.objects.create(addon=addon, app=1)
        CompatOverride.objects.create(addon=addon)
        FrozenAddon.objects.create(addon=addon)
        Persona.objects.create(addon=addon, persona_id=0)
        Preview.objects.create(addon=addon)

        AddonLog.objects.create(
            addon=addon, activity_log=ActivityLog.objects.create(action=0))
        RssKey.objects.create(addon=addon)
        SubmitStep.objects.create(addon=addon, step=0)

        # This should not throw any FK errors if all the cascades work.
        addon.delete()
        # Make sure it was actually a hard delete.
        assert not Addon.unfiltered.filter(pk=addon.pk).exists()

    def test_review_delete(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_PUBLIC)

        review = Review.objects.create(addon=addon, rating=1, body='foo',
                                       user=UserProfile.objects.create())

        flag = ReviewFlag(review=review)

        addon.delete()

        assert Addon.unfiltered.filter(pk=addon.pk).exists()
        assert not Review.objects.filter(pk=review.pk).exists()
        assert not ReviewFlag.objects.filter(pk=flag.pk).exists()

    def test_delete_with_deleted_versions(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = Version.objects.create(addon=addon, version="1.0")
        version.delete()
        addon.delete()
        assert Addon.unfiltered.filter(pk=addon.pk).exists()


class TestAddonFeatureCompatibility(TestCase):
    fixtures = ['base/addon_3615']

    def test_feature_compatibility_not_present(self):
        addon = Addon.objects.get(pk=3615)
        assert addon.feature_compatibility
        assert not addon.feature_compatibility.pk

    def test_feature_compatibility_present(self):
        addon = Addon.objects.get(pk=3615)
        AddonFeatureCompatibility.objects.create(addon=addon)
        assert addon.feature_compatibility
        assert addon.feature_compatibility.pk


class TestUpdateStatus(TestCase):

    def test_no_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        assert Addon.objects.no_cache().get(pk=addon.pk).status == (
            amo.STATUS_UNREVIEWED)
        Version.objects.create(addon=addon)
        assert Addon.objects.no_cache().get(pk=addon.pk).status == (
            amo.STATUS_NULL)

    def test_no_valid_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = Version.objects.create(addon=addon)
        f = File.objects.create(status=amo.STATUS_UNREVIEWED, version=version)
        addon.status = amo.STATUS_UNREVIEWED
        addon.save()
        assert Addon.objects.no_cache().get(pk=addon.pk).status == (
            amo.STATUS_UNREVIEWED)
        f.status = amo.STATUS_DISABLED
        f.save()
        assert Addon.objects.no_cache().get(pk=addon.pk).status == (
            amo.STATUS_NULL)


class TestGetVersion(TestCase):
    fixtures = ['base/addon_3615', ]

    def setUp(self):
        super(TestGetVersion, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def new_version(self, status):
        version = Version.objects.create(addon=self.addon)
        File.objects.create(version=version, status=status)
        return version

    def test_public_new_lite_version(self):
        self.new_version(amo.STATUS_LITE)
        assert self.addon.get_version() == self.version

    def test_public_new_nominated_version(self):
        self.new_version(amo.STATUS_NOMINATED)
        assert self.addon.get_version() == self.version

    def test_public_new_public_version(self):
        v = self.new_version(amo.STATUS_PUBLIC)
        assert self.addon.get_version() == v

    def test_public_new_unreviewed_version(self):
        self.new_version(amo.STATUS_UNREVIEWED)
        assert self.addon.get_version() == self.version

    def test_lite_new_unreviewed_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.new_version(amo.STATUS_UNREVIEWED)
        assert self.addon.get_version() == self.version

    def test_lite_new_lan_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_LITE_AND_NOMINATED)
        assert self.addon.get_version() == v

    def test_lite_new_lite_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_LITE)
        assert self.addon.get_version() == v

    def test_lite_new_full_version(self):
        self.addon.update(status=amo.STATUS_LITE)
        v = self.new_version(amo.STATUS_PUBLIC)
        assert self.addon.get_version() == v

    def test_lan_new_lite_version(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        v = self.new_version(amo.STATUS_LITE)
        assert self.addon.get_version() == v

    def test_lan_new_full_version(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        v = self.new_version(amo.STATUS_PUBLIC)
        assert self.addon.get_version() == v

    def test_should_promote_previous_valid_version_if_latest_is_disabled(self):
        self.new_version(amo.STATUS_DISABLED)
        assert self.addon.get_version() == self.version


class TestAddonGetURLPath(TestCase):

    def test_get_url_path(self):
        addon = Addon(slug='woo')
        assert addon.get_url_path() == '/en-US/firefox/addon/woo/'

    def test_get_url_path_more(self):
        addon = Addon(slug='yeah')
        assert addon.get_url_path(more=True) == (
            '/en-US/firefox/addon/yeah/more')

    def test_unlisted_addon_get_url_path(self):
        addon = Addon(slug='woo', is_listed=False)
        assert addon.get_url_path() == ''

    @patch.object(Addon, 'get_url_path', lambda self: '<script>xss</script>')
    def test_link_if_listed_else_text_xss(self):
        """We're playing extra safe here by making sure the data is escaped at
        the template level.

        We shouldn't have to worry about it though, because the "reverse" will
        prevent it.
        """
        addon = Addon(slug='woo')
        tpl = jingo.get_env().from_string(
            '{% from "devhub/includes/macros.html" '
            'import link_if_listed_else_text %}'
            '{{ link_if_listed_else_text(addon, "foo") }}')
        result = tpl.render({'addon': addon}).strip()
        assert result == '<a href="&lt;script&gt;xss&lt;/script&gt;">foo</a>'


class TestAddonModelsFeatured(TestCase):
    fixtures = ['base/appversion', 'base/users',
                'addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured']

    def setUp(self):
        super(TestAddonModelsFeatured, self).setUp()
        # Addon._featured keeps an in-process cache we need to clear.
        if hasattr(Addon, '_featured'):
            del Addon._featured

    def _test_featured_random(self):
        f = Addon.featured_random(amo.FIREFOX, 'en-US')
        assert sorted(f) == [1001, 1003, 2464, 3481, 7661, 15679]
        f = Addon.featured_random(amo.FIREFOX, 'fr')
        assert sorted(f) == [1001, 1003, 2464, 7661, 15679]
        f = Addon.featured_random(amo.THUNDERBIRD, 'en-US')
        assert f == []

    def test_featured_random(self):
        self._test_featured_random()


class TestBackupVersion(TestCase):
    fixtures = ['addons/update', 'base/appversion']

    def setUp(self):
        super(TestBackupVersion, self).setUp()
        self.version_1_2_0 = 105387
        self.addon = Addon.objects.get(pk=1865)
        set_user(None)

    def setup_new_version(self):
        for version in Version.objects.filter(pk__gte=self.version_1_2_0):
            appversion = version.apps.all()[0]
            appversion.min = AppVersion.objects.get(version='4.0b1')
            appversion.save()

    def test_no_current_version(self):
        for v in Version.objects.all():
            v.delete()
        self.addon.update(_current_version=None)
        assert self.addon.current_version is None

    def test_firefox_versions(self):
        self.setup_new_version()
        assert self.addon.update_version()
        current = self.addon.current_version.compatible_apps[amo.FIREFOX]
        assert current.max.version == '4.0b8pre'
        assert current.min.version == '3.0.12'

    def test_version_signals(self):
        self.addon.update(_current_version=None)
        self.setup_new_version()
        version = self.addon.versions.all()[0]
        assert not self.addon.current_version
        version.save()
        assert Addon.objects.get(pk=1865).current_version

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


class TestCategoryModel(TestCase):

    def test_category_url(self):
        """Every type must have a url path for its categories."""
        for t in amo.ADDON_TYPE.keys():
            if t == amo.ADDON_DICT:
                continue  # Language packs don't have categories.
            cat = Category(type=t, slug='omg')
            assert cat.get_url_path()


class TestPersonaModel(TestCase):
    fixtures = ['addons/persona']

    def setUp(self):
        super(TestPersonaModel, self).setUp()
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
        assert self.persona.thumb_url.endswith(self.p('preview.png'))
        assert self.persona.icon_url.endswith(self.p('icon.png'))
        assert self.persona.preview_url.endswith(self.p('preview.png'))
        assert self.persona.header_url.endswith(self.p('header.png'))
        assert self.persona.footer_url.endswith(self.p('footer.png'))

    def test_old_image_urls(self):
        assert self.persona.thumb_url.endswith(self.p('preview.jpg'))
        assert self.persona.icon_url.endswith(self.p('preview_small.jpg'))
        assert self.persona.preview_url.endswith(self.p('preview_large.jpg'))
        assert self.persona.header_url.endswith(self.p('header.png'))
        assert self.persona.footer_url.endswith(self.p('footer.png'))

    def test_update_url(self):
        with self.settings(LANGUAGE_CODE='fr', LANGUAGE_URL_MAP={}):
            url_ = self.persona.update_url
            assert url_.endswith('/fr/themes/update-check/15663')

    def test_json_data(self):
        self.persona.addon.all_categories = [Category(name='Yolo Art')]

        VAMO = 'https://vamo/%(locale)s/themes/update-check/%(id)d'

        with self.settings(LANGUAGE_CODE='fr',
                           LANGUAGE_URL_MAP={},
                           NEW_PERSONAS_UPDATE_URL=VAMO,
                           SITE_URL='https://omgsh.it'):
            data = self.persona.theme_data

            id_ = str(self.persona.addon.id)

            assert data['id'] == id_
            assert data['name'] == unicode(self.persona.addon.name)
            assert data['accentcolor'] == '#8d8d97'
            assert data['textcolor'] == '#ffffff'
            assert data['category'] == 'Yolo Art'
            assert data['author'] == 'persona_author'
            assert data['description'] == unicode(self.addon.description)

            assert data['headerURL'].startswith(
                '%s%s/header.png?' % (user_media_url('addons'), id_))
            assert data['footerURL'].startswith(
                '%s%s/footer.png?' % (user_media_url('addons'), id_))
            assert data['previewURL'].startswith(
                '%s%s/preview_large.jpg?' % (user_media_url('addons'), id_))
            assert data['iconURL'].startswith(
                '%s%s/preview_small.jpg?' % (user_media_url('addons'), id_))

            assert data['detailURL'] == (
                'https://omgsh.it%s' % self.persona.addon.get_url_path())
            assert data['updateURL'] == (
                'https://vamo/fr/themes/update-check/' + id_)
            assert data['version'] == '1.0'

    def test_json_data_new_persona(self):
        self.persona.persona_id = 0  # Make this a "new" theme.
        self.persona.save()

        self.persona.addon.all_categories = [Category(name='Yolo Art')]

        VAMO = 'https://vamo/%(locale)s/themes/update-check/%(id)d'

        with self.settings(LANGUAGE_CODE='fr',
                           LANGUAGE_URL_MAP={},
                           NEW_PERSONAS_UPDATE_URL=VAMO,
                           SITE_URL='https://omgsh.it'):
            data = self.persona.theme_data

            id_ = str(self.persona.addon.id)

            assert data['id'] == id_
            assert data['name'] == unicode(self.persona.addon.name)
            assert data['accentcolor'] == '#8d8d97'
            assert data['textcolor'] == '#ffffff'
            assert data['category'] == 'Yolo Art'
            assert data['author'] == 'persona_author'
            assert data['description'] == unicode(self.addon.description)

            assert data['headerURL'].startswith(
                '%s%s/header.png?' % (user_media_url('addons'), id_))
            assert data['footerURL'].startswith(
                '%s%s/footer.png?' % (user_media_url('addons'), id_))
            assert data['previewURL'].startswith(
                '%s%s/preview.png?' % (user_media_url('addons'), id_))
            assert data['iconURL'].startswith(
                '%s%s/icon.png?' % (user_media_url('addons'), id_))

            assert data['detailURL'] == (
                'https://omgsh.it%s' % self.persona.addon.get_url_path())
            assert data['updateURL'] == (
                'https://vamo/fr/themes/update-check/' + id_)
            assert data['version'] == '1.0'

    def test_image_urls_without_footer(self):
        self.persona.footer = ''
        self.persona.save()
        assert self.persona.footer_url == ''

    def test_json_data_without_footer(self):
        self.persona.footer = ''
        self.persona.save()
        data = self.persona.theme_data
        assert data['footerURL'] == ''
        assert data['footer'] == ''


class TestPreviewModel(TestCase):
    fixtures = ['base/previews']

    def test_as_dict(self):
        expect = ['caption', 'full', 'thumbnail']
        reality = sorted(Preview.objects.all()[0].as_dict().keys())
        assert expect == reality

    def test_filename(self):
        preview = Preview.objects.get(pk=24)
        assert preview.file_extension == 'png'
        preview.update(filetype='')
        assert preview.file_extension == 'png'
        preview.update(filetype='video/webm')
        assert preview.file_extension == 'webm'

    def test_filename_in_url(self):
        preview = Preview.objects.get(pk=24)
        preview.update(filetype='video/webm')
        assert 'png' in preview.thumbnail_path
        assert 'webm' in preview.image_path

    def check_delete(self, preview, filename):
        """
        Test that when the Preview object is deleted, its image and thumb
        are deleted from the filesystem.
        """
        try:
            with storage.open(filename, 'w') as f:
                f.write('sample data\n')
            assert storage.exists(filename)
            preview.delete()
            assert not storage.exists(filename)
        finally:
            if storage.exists(filename):
                storage.delete(filename)

    def test_delete_image(self):
        preview = Preview.objects.get(pk=24)
        self.check_delete(preview, preview.image_path)

    def test_delete_thumbnail(self):
        preview = Preview.objects.get(pk=24)
        self.check_delete(preview, preview.thumbnail_path)


class TestAddonDependencies(TestCase):
    fixtures = ['base/appversion',
                'base/users',
                'base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_6704_grapple',
                'base/addon_4664_twitterbar']

    def test_dependencies(self):
        ids = [3615, 3723, 4664, 6704]
        addon = Addon.objects.get(id=5299)
        dependencies = Addon.objects.in_bulk(ids)

        for dependency in dependencies.values():
            AddonDependency(addon=addon, dependent_addon=dependency).save()

        # Make sure all dependencies were saved correctly.
        assert sorted([a.id for a in addon.dependencies.all()]) == sorted(ids)

        # Add-on 3723 is disabled and won't show up in `all_dependencies`
        # property.
        assert addon.all_dependencies == [
            dependencies[3615], dependencies[4664], dependencies[6704]]

        # Adding another dependency won't change anything because we're already
        # at the maximum (3).
        new_dep = amo.tests.addon_factory()
        AddonDependency.objects.create(addon=addon, dependent_addon=new_dep)
        assert addon.all_dependencies == [
            dependencies[3615], dependencies[4664], dependencies[6704]]

        # Removing the first dependency will allow the one we just created to
        # be visible.
        dependencies[3615].delete()
        assert addon.all_dependencies == [
            dependencies[4664], dependencies[6704], new_dep]

    def test_unique_dependencies(self):
        a = Addon.objects.get(id=5299)
        b = Addon.objects.get(id=3615)
        AddonDependency.objects.create(addon=a, dependent_addon=b)
        assert list(a.dependencies.values_list('id', flat=True)) == [3615]
        with self.assertRaises(IntegrityError):
            AddonDependency.objects.create(addon=a, dependent_addon=b)


class TestListedAddonTwoVersions(TestCase):
    fixtures = ['addons/listed-two-versions']

    def test_listed_two_versions(self):
        Addon.objects.get(id=2795)  # bug 563967


class TestAddonFromUpload(UploadTest):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonFromUpload, self).setUp()
        u = UserProfile.objects.get(pk=999)
        set_user(u)
        self.platform = amo.PLATFORM_MAC.id
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application=1, version=version)
        self.addCleanup(translation.deactivate)

    def manifest(self, basename):
        return os.path.join(
            settings.ROOT, 'src', 'olympia', 'devhub', 'tests', 'addons',
            basename)

    def test_blacklisted_guid(self):
        """New deletions won't be added to BlacklistedGuid but legacy support
        should still be tested."""
        BlacklistedGuid.objects.create(guid='guid@xpi')
        with self.assertRaises(forms.ValidationError) as e:
            Addon.from_upload(self.get_upload('extension.xpi'),
                              [self.platform])
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid(self):
        # Upload addon so we can delete it.
        deleted = Addon.from_upload(self.get_upload('extension.xpi'),
                                    [self.platform])
        deleted.update(status=amo.STATUS_PUBLIC)
        deleted.delete()
        assert deleted.guid == 'guid@xpi'

        # Now upload the same add-on again (so same guid).
        with self.assertRaises(forms.ValidationError) as e:
            Addon.from_upload(self.get_upload('extension.xpi'),
                              [self.platform])
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid_same_author(self):
        # Upload addon so we can delete it.
        deleted = Addon.from_upload(self.get_upload('extension.xpi'),
                                    [self.platform])
        # Claim the add-on.
        AddonUser(addon=deleted, user=UserProfile.objects.get(pk=999)).save()
        deleted.update(status=amo.STATUS_PUBLIC)
        deleted.delete()
        assert deleted.guid == 'guid@xpi'

        # Now upload the same add-on again (so same guid), checking no
        # validationError is raised this time.
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        deleted.reload()
        assert addon.guid == 'guid@xpi'
        assert deleted.guid == 'guid-reused-by-pk-%s' % addon.pk

    def test_old_soft_deleted_addons_and_upload_non_extension(self):
        """We used to just null out GUIDs on soft deleted addons. This test
        makes sure we don't fail badly when uploading an add-on which isn't an
        extension (has no GUID).
        See https://github.com/mozilla/addons-server/issues/1659."""
        # Upload a couple of addons so we can pretend they were soft deleted.
        deleted1 = Addon.from_upload(
            self.get_upload('extension.xpi'), [self.platform])
        deleted2 = Addon.from_upload(
            self.get_upload('alt-rdf.xpi'), [self.platform])
        AddonUser(addon=deleted1, user=UserProfile.objects.get(pk=999)).save()
        AddonUser(addon=deleted2, user=UserProfile.objects.get(pk=999)).save()

        # Soft delete them like they were before, by nullifying their GUIDs.
        deleted1.update(status=amo.STATUS_PUBLIC, guid=None)
        deleted2.update(status=amo.STATUS_PUBLIC, guid=None)

        # Now upload a new add-on which isn't an extension, and has no GUID.
        # This fails if we try to reclaim the GUID from deleted add-ons: the
        # GUID is None, so it'll try to get the add-on that has a GUID which is
        # None, but many are returned. So make sure we're not trying to reclaim
        # the GUID.
        Addon.from_upload(
            self.get_upload('search.xml'), [self.platform])

    def test_xpi_attributes(self):
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        assert addon.name == 'xpi name'
        assert addon.guid == 'guid@xpi'
        assert addon.type == amo.ADDON_EXTENSION
        assert addon.status == amo.STATUS_NULL
        assert addon.homepage == 'http://homepage.com'
        assert addon.summary == 'xpi description'
        assert addon.description is None
        assert addon.slug == 'xpi-name'

    def test_xpi_version(self):
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        v = addon.versions.get()
        assert v.version == '0.1'
        assert v.files.get().platform == self.platform
        assert v.files.get().status == amo.STATUS_UNREVIEWED

    def test_xpi_for_multiple_platforms(self):
        platforms = [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id]
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  platforms)
        v = addon.versions.get()
        assert sorted([f.platform for f in v.all_files]) == (
            sorted(platforms))

    def test_search_attributes(self):
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        assert addon.name == 'search tool'
        assert addon.guid is None
        assert addon.type == amo.ADDON_SEARCH
        assert addon.status == amo.STATUS_NULL
        assert addon.homepage is None
        assert addon.description is None
        assert addon.slug == 'search-tool'
        assert addon.summary == 'Search Engine for Firefox'

    def test_search_version(self):
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        v = addon.versions.get()
        assert v.version == datetime.now().strftime('%Y%m%d')
        assert v.files.get().platform == amo.PLATFORM_ALL.id
        assert v.files.get().status == amo.STATUS_UNREVIEWED

    def test_no_homepage(self):
        addon = Addon.from_upload(self.get_upload('extension-no-homepage.xpi'),
                                  [self.platform])
        assert addon.homepage is None

    def test_default_locale(self):
        # Make sure default_locale follows the active translation.
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        assert addon.default_locale == 'en-US'

        translation.activate('es')
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform])
        assert addon.default_locale == 'es'

    def test_is_listed(self):
        # By default, the addon is listed.
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform])
        assert addon.is_listed

    def test_is_not_listed(self):
        # An addon can be explicitely unlisted.
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  [self.platform], is_listed=False)
        assert not addon.is_listed

    def test_validation_completes(self):
        upload = self.get_upload('extension.xpi')
        assert not upload.validation_timeout
        addon = Addon.from_upload(upload, [self.platform])
        assert not addon.admin_review

    def test_validation_timeout(self):
        upload = self.get_upload('extension.xpi')
        validation = json.loads(upload.validation)
        timeout_message = {
            'id': ['validator', 'unexpected_exception', 'validation_timeout'],
        }
        validation['messages'] = [timeout_message] + validation['messages']
        upload.validation = json.dumps(validation)
        assert upload.validation_timeout
        addon = Addon.from_upload(upload, [self.platform])
        assert addon.admin_review

    def test_webextension_generate_guid(self):
        addon = Addon.from_upload(
            self.get_upload('webextension_no_id.xpi'),
            [self.platform])

        assert addon.guid is not None
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

        # Uploading the same addon without a id works.
        new_addon = Addon.from_upload(
            self.get_upload('webextension_no_id.xpi'),
            [self.platform])
        assert new_addon.guid is not None
        assert new_addon.guid != addon.guid
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

    def test_webextension_reuse_guid(self):
        addon = Addon.from_upload(
            self.get_upload('webextension.xpi'),
            [self.platform])

        assert addon.guid == '@webextension-guid'

        # Uploading the same addon with pre-existing id fails
        with self.assertRaises(forms.ValidationError) as e:
            Addon.from_upload(self.get_upload('webextension.xpi'),
                              [self.platform])
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_basic_extension_is_marked_as_e10s_unknown(self):
        # extension.xpi does not have multiprocessCompatible set to true, so
        # it's marked as not-compatible.
        addon = Addon.from_upload(
            self.get_upload('extension.xpi'),
            [self.platform])

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_UNKNOWN

    def test_extension_is_marked_as_e10s_incompatible(self):
        addon = Addon.from_upload(
            self.get_upload('multiprocess_incompatible_extension.xpi'),
            [self.platform])

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_INCOMPATIBLE

    def test_multiprocess_extension_is_marked_as_e10s_compatible(self):
        addon = Addon.from_upload(
            self.get_upload('multiprocess_compatible_extension.xpi'),
            [self.platform])

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_COMPATIBLE

    def test_webextension_is_marked_as_e10s_compatible(self):
        addon = Addon.from_upload(
            self.get_upload('webextension.xpi'),
            [self.platform])

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_COMPATIBLE_WEBEXTENSION

    def test_webextension_resolve_translations(self):
        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            [self.platform])

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'
        assert addon.name == 'Notify link clicks i18n'
        assert addon.summary == (
            'Shows a notification when the user clicks on links.')

        # Make sure we set the correct slug
        assert addon.slug == 'notify-link-clicks-i18n'

        translation.activate('de')
        addon.reload()
        assert addon.name == 'Meine Beispielerweiterung'
        assert addon.summary == u'Benachrichtigt den Benutzer über Linkklicks'

    @patch('olympia.addons.models.parse_addon')
    def test_webext_resolve_translations_corrects_locale(self, parse_addon):
        """Make sure we correct invalid `default_locale` values"""
        parse_addon.return_value = {
            'default_locale': u'en',
            'e10s_compatibility': 2,
            'guid': u'notify-link-clicks-i18n@mozilla.org',
            'name': u'__MSG_extensionName__',
            'is_webextension': True,
            'type': 1,
            'apps': [],
            'summary': u'__MSG_extensionDescription__',
            'version': u'1.0',
            'homepage': '...'
        }

        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            [self.platform])

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'

    @patch('olympia.addons.models.parse_addon')
    def test_webext_resolve_translations_unknown_locale(self, parse_addon):
        """Make sure we use our default language as default
        for invalid locales
        """
        parse_addon.return_value = {
            'default_locale': u'xxx',
            'e10s_compatibility': 2,
            'guid': u'notify-link-clicks-i18n@mozilla.org',
            'name': u'__MSG_extensionName__',
            'is_webextension': True,
            'type': 1,
            'apps': [],
            'summary': u'__MSG_extensionDescription__',
            'version': u'1.0',
            'homepage': '...'
        }

        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            [self.platform])

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'


REDIRECT_URL = 'https://outgoing.prod.mozaws.net/v1/'


class TestCharity(TestCase):
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


class TestFrozenAddons(TestCase):

    def test_immediate_freeze(self):
        # Adding a FrozenAddon should immediately drop the addon's hotness.
        a = Addon.objects.create(type=1, hotness=22)
        FrozenAddon.objects.create(addon=a)
        assert Addon.objects.get(id=a.id).hotness == 0


class TestRemoveLocale(TestCase):

    def test_remove(self):
        a = Addon.objects.create(type=1)
        a.name = {'en-US': 'woo', 'el': 'yeah'}
        a.description = {'en-US': 'woo', 'el': 'yeah', 'he': 'ola'}
        a.save()
        a.remove_locale('el')
        qs = (Translation.objects.filter(localized_string__isnull=False)
              .values_list('locale', flat=True))
        assert sorted(qs.filter(id=a.name_id)) == ['en-US']
        assert sorted(qs.filter(id=a.description_id)) == ['en-US', 'he']

    def test_remove_version_locale(self):
        addon = Addon.objects.create(type=amo.ADDON_THEME)
        version = Version.objects.create(addon=addon)
        version.releasenotes = {'fr': 'oui'}
        version.save()
        addon.remove_locale('fr')
        assert not (Translation.objects.filter(localized_string__isnull=False)
                               .values_list('locale', flat=True))


class TestAddonWatchDisabled(TestCase):

    def setUp(self):
        super(TestAddonWatchDisabled, self).setUp()
        self.addon = Addon(type=amo.ADDON_THEME, disabled_by_user=False,
                           status=amo.STATUS_PUBLIC)
        self.addon.save()

    @patch('olympia.addons.models.File.objects.filter')
    def test_no_disabled_change(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.save()
        assert not mock.unhide_disabled_file.called
        assert not mock.hide_disabled_file.called

    @patch('olympia.addons.models.File.objects.filter')
    def test_disable_addon(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.update(disabled_by_user=True)
        assert not mock.unhide_disabled_file.called
        assert mock.hide_disabled_file.called

    @patch('olympia.addons.models.File.objects.filter')
    def test_admin_disable_addon(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.update(status=amo.STATUS_DISABLED)
        assert not mock.unhide_disabled_file.called
        assert mock.hide_disabled_file.called

    @patch('olympia.addons.models.File.objects.filter')
    def test_enable_addon(self, file_mock):
        mock = Mock()
        file_mock.return_value = [mock]
        self.addon.update(status=amo.STATUS_DISABLED)
        mock.reset_mock()
        self.addon.update(status=amo.STATUS_PUBLIC)
        assert mock.unhide_disabled_file.called
        assert not mock.hide_disabled_file.called


class TestAddonWatchDeveloperNotes(TestCase):

    def make_addon(self, **kwargs):
        addon = Addon(type=amo.ADDON_EXTENSION, status=amo.STATUS_PUBLIC,
                      **kwargs)
        addon.save()
        addon.versions.create(has_info_request=True)
        addon.versions.create(has_info_request=False)
        addon.versions.create(has_info_request=True)
        return addon

    def assertHasInfoSet(self, addon):
        assert any([v.has_info_request for v in addon.versions.all()])

    def assertHasInfoNotSet(self, addon):
        assert all([not v.has_info_request for v in addon.versions.all()])

    def test_has_info_save(self):
        """Test saving without a change doesn't clear has_info_request."""
        addon = self.make_addon()
        self.assertHasInfoSet(addon)
        addon.save()
        self.assertHasInfoSet(addon)

    def test_has_info_update_whiteboard(self):
        """Test saving with a change to whiteboard clears has_info_request."""
        addon = self.make_addon()
        self.assertHasInfoSet(addon)
        addon.whiteboard = 'Info about things.'
        addon.save()
        self.assertHasInfoNotSet(addon)

    def test_has_info_update_whiteboard_no_change(self):
        """Test saving without a change to whiteboard doesn't clear
        has_info_request."""
        addon = self.make_addon(whiteboard='Info about things.')
        self.assertHasInfoSet(addon)
        addon.whiteboard = 'Info about things.'
        addon.save()
        self.assertHasInfoSet(addon)

    def test_has_info_whiteboard_removed(self):
        """Test saving with an empty whiteboard doesn't clear
        has_info_request."""
        addon = self.make_addon(whiteboard='Info about things.')
        self.assertHasInfoSet(addon)
        addon.whiteboard = ''
        addon.save()
        self.assertHasInfoSet(addon)

    def test_has_info_update_developer_comments(self):
        """Test saving with a change to developer_comments clears
        has_info_request."""
        addon = self.make_addon()
        self.assertHasInfoSet(addon)
        addon.developer_comments = 'Things are thing-like.'
        addon.save()
        self.assertHasInfoNotSet(addon)

    def test_has_info_update_developer_comments_again(self):
        """Test saving a change to developer_comments when developer_comments
        was already set clears has_info_request (developer_comments is a
        PurifiedField so it is really just an id)."""
        addon = self.make_addon(developer_comments='Wat things like.')
        self.assertHasInfoSet(addon)
        addon.developer_comments = 'Things are thing-like.'
        addon.save()
        self.assertHasInfoNotSet(addon)

    def test_has_info_update_developer_comments_no_change(self):
        """Test saving without a change to developer_comments doesn't clear
        has_info_request."""
        addon = self.make_addon(developer_comments='Things are thing-like.')
        self.assertHasInfoSet(addon)
        addon.developer_comments = 'Things are thing-like.'
        addon.save()
        self.assertHasInfoSet(addon)

    def test_has_info_remove_developer_comments(self):
        """Test saving with an empty developer_comments doesn't clear
        has_info_request."""
        addon = self.make_addon(developer_comments='Things are thing-like.')
        self.assertHasInfoSet(addon)
        addon.developer_comments = ''
        addon.save()
        self.assertHasInfoSet(addon)


class TestTrackAddonStatusChange(TestCase):

    def create_addon(self, **kwargs):
        kwargs.setdefault('type', amo.ADDON_EXTENSION)
        addon = Addon(**kwargs)
        addon.save()
        return addon

    def test_increment_new_status(self):
        with patch('olympia.addons.models.track_addon_status_change') as mock_:
            addon = self.create_addon()
        mock_.assert_called_with(addon)

    def test_increment_updated_status(self):
        addon = self.create_addon()
        with patch('olympia.addons.models.track_addon_status_change') as mock_:
            addon.update(status=amo.STATUS_PUBLIC)

        addon.reload()
        mock_.call_args[0][0].status == addon.status

    def test_ignore_non_status_changes(self):
        addon = self.create_addon()
        with patch('olympia.addons.models.track_addon_status_change') as mock_:
            addon.update(type=amo.ADDON_THEME)
        assert not mock_.called, (
            'Unexpected call: {}'.format(self.mock_incr.call_args)
        )

    def test_increment_all_addon_statuses(self):
        addon = self.create_addon(status=amo.STATUS_PUBLIC)
        with patch('olympia.addons.models.statsd.incr') as mock_incr:
            track_addon_status_change(addon)
        mock_incr.assert_any_call(
            'addon_status_change.all.status_{}'.format(amo.STATUS_PUBLIC)
        )

    def test_increment_listed_addon_statuses(self):
        addon = self.create_addon(is_listed=True)
        with patch('olympia.addons.models.statsd.incr') as mock_incr:
            track_addon_status_change(addon)
        mock_incr.assert_any_call(
            'addon_status_change.listed.status_{}'.format(addon.status)
        )

    def test_increment_unlisted_addon_statuses(self):
        addon = self.create_addon(is_listed=False)
        with patch('olympia.addons.models.statsd.incr') as mock_incr:
            track_addon_status_change(addon)
        mock_incr.assert_any_call(
            'addon_status_change.unlisted.status_{}'.format(addon.status)
        )


class TestSearchSignals(amo.tests.ESTestCase):

    def setUp(self):
        super(TestSearchSignals, self).setUp()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.empty_index('default')

    def test_no_addons(self):
        assert Addon.search_public().count() == 0

    def test_create(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo',
                                     status=amo.STATUS_PUBLIC)
        self.refresh()
        assert Addon.search_public().count() == 1
        assert Addon.search_public().query(name='woo')[0].id == addon.id

    def test_update(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo',
                                     status=amo.STATUS_PUBLIC)
        self.refresh()
        assert Addon.search_public().count() == 1

        addon.name = 'yeah'
        addon.save()
        self.refresh()

        assert Addon.search_public().count() == 1
        assert Addon.search_public().query(name='woo').count() == 0
        assert Addon.search_public().query(name='yeah')[0].id == addon.id

    def test_user_disable(self):
        """Test that add-ons are removed from search results after being
        disabled by their developers."""
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo',
                                     status=amo.STATUS_PUBLIC)
        self.refresh()
        assert Addon.search_public().count() == 1

        addon.disabled_by_user = True
        addon.save()
        self.refresh()

        assert Addon.search_public().count() == 0

    def test_switch_to_unlisted(self):
        """Test that add-ons are removed from search results after being
        switched to unlisted."""
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo',
                                     status=amo.STATUS_PUBLIC)
        self.refresh()
        assert Addon.search_public().count() == 1

        addon.is_listed = False
        addon.save()
        self.refresh()

        assert Addon.search_public().count() == 0

    def test_switch_to_listed(self):
        """Test that add-ons created as unlisted do not appear in search
        results until switched to listed."""
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo',
                                     status=amo.STATUS_PUBLIC, is_listed=False)
        self.refresh()
        assert Addon.search_public().count() == 0

        addon.is_listed = True
        addon.save()
        self.refresh()

        assert Addon.search_public().count() == 1

    def test_delete(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION, name='woo',
                                     status=amo.STATUS_PUBLIC)
        self.refresh()
        assert Addon.search_public().count() == 1

        addon.delete('woo')
        self.refresh()
        assert Addon.search_public().count() == 0


class TestLanguagePack(TestCase, amo.tests.AMOPaths):

    def setUp(self):
        super(TestLanguagePack, self).setUp()
        self.addon = amo.tests.addon_factory(type=amo.ADDON_LPAPP,
                                             status=amo.STATUS_PUBLIC)
        self.platform_all = amo.PLATFORM_ALL.id
        self.platform_mob = amo.PLATFORM_ANDROID.id
        self.version = self.addon.current_version

    def test_extract(self):
        File.objects.create(platform=self.platform_mob, version=self.version,
                            filename=self.xpi_path('langpack-localepicker'),
                            status=amo.STATUS_PUBLIC)
        assert self.addon.reload().get_localepicker()
        assert 'title=Select a language' in self.addon.get_localepicker()

    def test_extract_no_file(self):
        File.objects.create(platform=self.platform_mob, version=self.version,
                            filename=self.xpi_path('langpack'),
                            status=amo.STATUS_PUBLIC)
        assert self.addon.reload().get_localepicker() == ''

    def test_extract_no_files(self):
        assert self.addon.get_localepicker() == ''

    def test_extract_not_language_pack(self):
        File.objects.create(platform=self.platform_mob, version=self.version,
                            filename=self.xpi_path('langpack-localepicker'),
                            status=amo.STATUS_PUBLIC)
        assert self.addon.reload().get_localepicker()
        self.addon.update(type=amo.ADDON_EXTENSION)
        assert self.addon.get_localepicker() == ''

    def test_extract_not_platform_mobile(self):
        File.objects.create(platform=self.platform_all, version=self.version,
                            filename=self.xpi_path('langpack-localepicker'),
                            status=amo.STATUS_PUBLIC)
        assert self.addon.reload().get_localepicker() == ''


class TestCompatOverride(TestCase):

    def setUp(self):
        super(TestCompatOverride, self).setUp()
        self.app = amo.APP_IDS[1]

        one = CompatOverride.objects.create(guid='one')
        CompatOverrideRange.objects.create(compat=one, app=self.app.id)

        two = CompatOverride.objects.create(guid='two')
        CompatOverrideRange.objects.create(compat=two, app=self.app.id,
                                           min_version='1', max_version='2')
        CompatOverrideRange.objects.create(compat=two, app=self.app.id,
                                           min_version='1', max_version='2',
                                           min_app_version='3',
                                           max_app_version='4')

    def check(self, obj, **kw):
        """Check that key/value pairs in kw match attributes of obj."""
        for key, expected in kw.items():
            actual = getattr(obj, key)
            assert actual == expected

    def test_is_hosted(self):
        c = CompatOverride.objects.create(guid='a')
        assert not c.is_hosted()

        Addon.objects.create(type=1, guid='b')
        c = CompatOverride.objects.create(guid='b')
        assert c.is_hosted()

    def test_override_type(self):
        one = CompatOverride.objects.get(guid='one')

        # The default is incompatible.
        c = CompatOverrideRange.objects.create(compat=one, app=1)
        assert c.override_type() == 'incompatible'

        c = CompatOverrideRange.objects.create(compat=one, app=1, type=0)
        assert c.override_type() == 'compatible'

    def test_guid_match(self):
        # We hook up the add-on automatically if we see a matching guid.
        addon = Addon.objects.create(id=1, guid='oh yeah', type=1)
        c = CompatOverride.objects.create(guid=addon.guid)
        assert c.addon_id == addon.id

        c = CompatOverride.objects.create(guid='something else')
        assert c.addon is None

    def test_transformer(self):
        compats = list(CompatOverride.objects
                       .transform(CompatOverride.transformer))
        ranges = list(CompatOverrideRange.objects.all())
        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            for c in compats:
                assert c.compat_ranges == (
                    [r for r in ranges if r.compat_id == c.id])

    def test_collapsed_ranges(self):
        # Test that we get back the right structures from collapsed_ranges().
        c = CompatOverride.objects.get(guid='one')
        r = c.collapsed_ranges()

        assert len(r) == 1
        compat_range = r[0]
        self.check(compat_range, type='incompatible', min='0', max='*')

        assert len(compat_range.apps) == 1
        self.check(compat_range.apps[0], app=amo.FIREFOX, min='0', max='*')

    def test_collapsed_ranges_multiple_versions(self):
        c = CompatOverride.objects.get(guid='one')
        CompatOverrideRange.objects.create(compat=c, app=1,
                                           min_version='1', max_version='2',
                                           min_app_version='3',
                                           max_app_version='3.*')
        r = c.collapsed_ranges()

        assert len(r) == 2

        self.check(r[0], type='incompatible', min='0', max='*')
        assert len(r[0].apps) == 1
        self.check(r[0].apps[0], app=amo.FIREFOX, min='0', max='*')

        self.check(r[1], type='incompatible', min='1', max='2')
        assert len(r[1].apps) == 1
        self.check(r[1].apps[0], app=amo.FIREFOX, min='3', max='3.*')

    def test_collapsed_ranges_different_types(self):
        # If the override ranges have different types they should be separate
        # entries.
        c = CompatOverride.objects.get(guid='one')
        CompatOverrideRange.objects.create(compat=c, app=1, type=0,
                                           min_app_version='3',
                                           max_app_version='3.*')
        r = c.collapsed_ranges()

        assert len(r) == 2

        self.check(r[0], type='compatible', min='0', max='*')
        assert len(r[0].apps) == 1
        self.check(r[0].apps[0], app=amo.FIREFOX, min='3', max='3.*')

        self.check(r[1], type='incompatible', min='0', max='*')
        assert len(r[1].apps) == 1
        self.check(r[1].apps[0], app=amo.FIREFOX, min='0', max='*')

    def test_collapsed_ranges_multiple_apps(self):
        c = CompatOverride.objects.get(guid='two')
        r = c.collapsed_ranges()

        assert len(r) == 1
        compat_range = r[0]
        self.check(compat_range, type='incompatible', min='1', max='2')

        assert len(compat_range.apps) == 2
        self.check(compat_range.apps[0], app=amo.FIREFOX, min='0', max='*')
        self.check(compat_range.apps[1], app=amo.FIREFOX, min='3', max='4')

    def test_collapsed_ranges_multiple_versions_and_apps(self):
        c = CompatOverride.objects.get(guid='two')
        CompatOverrideRange.objects.create(min_version='5', max_version='6',
                                           compat=c, app=1)
        r = c.collapsed_ranges()

        assert len(r) == 2
        self.check(r[0], type='incompatible', min='1', max='2')

        assert len(r[0].apps) == 2
        self.check(r[0].apps[0], app=amo.FIREFOX, min='0', max='*')
        self.check(r[0].apps[1], app=amo.FIREFOX, min='3', max='4')

        self.check(r[1], type='incompatible', min='5', max='6')
        assert len(r[1].apps) == 1
        self.check(r[1].apps[0], app=amo.FIREFOX, min='0', max='*')


class TestIncompatibleVersions(TestCase):

    def setUp(self):
        super(TestIncompatibleVersions, self).setUp()
        self.app = amo.APP_IDS[amo.FIREFOX.id]
        self.addon = Addon.objects.create(guid='r@b', type=amo.ADDON_EXTENSION)

    def test_signals_min(self):
        assert IncompatibleVersions.objects.count() == 0

        c = CompatOverride.objects.create(guid='r@b')
        CompatOverrideRange.objects.create(compat=c, app=self.app.id,
                                           min_version='0',
                                           max_version='1.0')

        # Test the max version matched.
        version1 = Version.objects.create(id=2, addon=self.addon,
                                          version='1.0')
        assert IncompatibleVersions.objects.filter(
            version=version1).count() == 1
        assert IncompatibleVersions.objects.count() == 1

        # Test the lower range.
        version2 = Version.objects.create(id=1, addon=self.addon,
                                          version='0.5')
        assert IncompatibleVersions.objects.filter(
            version=version2).count() == 1
        assert IncompatibleVersions.objects.count() == 2

        # Test delete signals.
        version1.delete()
        assert IncompatibleVersions.objects.count() == 1

        version2.delete()
        assert IncompatibleVersions.objects.count() == 0

    def test_signals_max(self):
        assert IncompatibleVersions.objects.count() == 0

        c = CompatOverride.objects.create(guid='r@b')
        CompatOverrideRange.objects.create(compat=c, app=self.app.id,
                                           min_version='1.0',
                                           max_version='*')

        # Test the min_version matched.
        version1 = Version.objects.create(addon=self.addon, version='1.0')
        assert IncompatibleVersions.objects.filter(
            version=version1).count() == 1
        assert IncompatibleVersions.objects.count() == 1

        # Test the upper range.
        version2 = Version.objects.create(addon=self.addon, version='99.0')
        assert IncompatibleVersions.objects.filter(
            version=version2).count() == 1
        assert IncompatibleVersions.objects.count() == 2

        # Test delete signals.
        version1.delete()
        assert IncompatibleVersions.objects.count() == 1

        version2.delete()
        assert IncompatibleVersions.objects.count() == 0


class TestQueue(TestCase):

    def test_in_queue(self):
        addon = Addon.objects.create(guid='f', type=amo.ADDON_EXTENSION)
        assert not addon.in_escalation_queue()
        EscalationQueue.objects.create(addon=addon)
        assert addon.in_escalation_queue()
