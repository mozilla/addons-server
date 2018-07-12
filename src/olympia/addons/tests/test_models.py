# -*- coding: utf-8 -*-
import json
import os
import time

from datetime import datetime, timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core import mail

from django.db import IntegrityError
from django.utils import translation

import pytest
from mock import Mock, patch

from olympia import amo, core
from olympia.addons import models as addons_models
from olympia.activity.models import ActivityLog, AddonLog
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonCategory, AddonDependency,
    AddonFeatureCompatibility, AddonReviewerFlags, AddonUser, AppSupport,
    Category, CompatOverride, CompatOverrideRange, DeniedGuid, DeniedSlug,
    FrozenAddon, IncompatibleVersions, MigratedLWT, Persona, Preview,
    track_addon_status_change)
from olympia.amo.templatetags.jinja_helpers import absolutify, user_media_url
from olympia.amo.tests import (
    TestCase, addon_factory, collection_factory, version_factory)
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection, FeaturedCollection
from olympia.constants.categories import CATEGORIES
from olympia.devhub.models import RssKey
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.ratings.models import Rating, RatingFlag
from olympia.translations.models import (
    Translation, TranslationSequence, delete_translation)
from olympia.users.models import UserProfile
from olympia.versions.compare import version_int
from olympia.versions.models import (
    ApplicationsVersions, Version, VersionPreview)


class TestCleanSlug(TestCase):

    def test_clean_slug_new_object(self):
        # Make sure there's at least an addon with the "addon" slug, subsequent
        # ones should be "addon-1", "addon-2" ...
        a = Addon.objects.create(name='Addon')
        assert a.slug == 'addon'

        # Start with a first clash. This should give us 'addon-1".
        # We're not saving yet, we're testing the slug creation without an id.
        b = Addon(name='Addon')
        b.clean_slug()
        assert b.slug == 'addon1'
        # Now save the instance to the database for future clashes.
        b.save()

        # Test on another object without an id.
        c = Addon(name='Addon')
        c.clean_slug()
        assert c.slug == 'addon2'

        # Even if an addon is deleted, don't clash with its slug.
        c.status = amo.STATUS_DELETED
        # Now save the instance to the database for future clashes.
        c.save()

        # And yet another object without an id. Make sure we're not trying to
        # assign the 'addon-2' slug from the deleted addon.
        d = Addon(name='Addon')
        d.clean_slug()
        assert d.slug == 'addon3'

    def test_clean_slug_no_name(self):
        # Create an addon and save it to have an id.
        a = Addon.objects.create()
        # Start over: don't use the name nor the id to generate the slug.
        a.slug = a.name = ''
        a.clean_slug()

        # Slugs that are generated from add-ons without an name use
        # uuid without the node bit so have the length 20.
        assert len(a.slug) == 20

    def test_clean_slug_with_name(self):
        # Make sure there's at least an addon with the 'fooname' slug,
        # subsequent ones should be 'fooname-1', 'fooname-2' ...
        a = Addon.objects.create(name='fooname')
        assert a.slug == 'fooname'

        b = Addon(name='fooname')
        b.clean_slug()
        assert b.slug == 'fooname1'

    def test_clean_slug_with_slug(self):
        # Make sure there's at least an addon with the 'fooslug' slug,
        # subsequent ones should be 'fooslug-1', 'fooslug-2' ...
        a = Addon.objects.create(name='fooslug')
        assert a.slug == 'fooslug'

        b = Addon(name='fooslug')
        b.clean_slug()
        assert b.slug == 'fooslug1'

    def test_clean_slug_denied_slug(self):
        denied_slug = 'foodenied'
        DeniedSlug.objects.create(name=denied_slug)

        a = Addon(slug=denied_slug)
        a.clean_slug()
        # Blacklisted slugs (like 'activate" or IDs) have a "~" appended to
        # avoid clashing with URLs.
        assert a.slug == '%s~' % denied_slug
        # Now save the instance to the database for future clashes.
        a.save()

        b = Addon(slug=denied_slug)
        b.clean_slug()
        assert b.slug == '%s~1' % denied_slug

    def test_clean_slug_denied_slug_long_slug(self):
        long_slug = 'this_is_a_very_long_slug_that_is_longer_than_thirty_chars'
        DeniedSlug.objects.create(name=long_slug[:30])

        # If there's no clashing slug, just append a '~'.
        a = Addon.objects.create(slug=long_slug[:30])
        assert a.slug == '%s~' % long_slug[:29]

        # If there's a clash, use the standard clash resolution.
        a = Addon.objects.create(slug=long_slug[:30])
        assert a.slug == '%s1' % long_slug[:27]

    def test_clean_slug_long_slug(self):
        long_slug = 'this_is_a_very_long_slug_that_is_longer_than_thirty_chars'

        # If there's no clashing slug, don't over-shorten it.
        a = Addon.objects.create(slug=long_slug)
        assert a.slug == long_slug[:30]

        # Now that there is a clash, test the clash resolution.
        b = Addon(slug=long_slug)
        b.clean_slug()
        assert b.slug == '%s1' % long_slug[:27]

    def test_clean_slug_always_slugify(self):
        illegal_chars = 'some spaces and !?@'

        # Slugify if there's a slug provided.
        a = Addon(slug=illegal_chars)
        a.clean_slug()
        assert a.slug.startswith('some-spaces-and'), a.slug

        # Also slugify if there's no slug provided.
        b = Addon(name=illegal_chars)
        b.clean_slug()
        assert b.slug.startswith('some-spaces-and'), b.slug

    @patch.object(addons_models, 'MAX_SLUG_INCREMENT', 99)
    @patch.object(
        addons_models, 'SLUG_INCREMENT_SUFFIXES', set(range(1, 99 + 1)))
    def test_clean_slug_worst_case_scenario(self):
        long_slug = 'this_is_a_very_long_slug_that_is_longer_than_thirty_chars'

        # Generate 100 addons with this very long slug. We should encounter the
        # worst case scenario where all the available clashes have been
        # avoided. Check the comment in addons.models.clean_slug, in the 'else'
        # part of the 'for" loop checking for available slugs not yet assigned.
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

    def test_clean_slug_unicode(self):
        addon = Addon.objects.create(name=u'Addön 1')
        assert addon.slug == u'addön-1'


class TestAddonManager(TestCase):
    fixtures = ['base/appversion', 'base/users',
                'base/addon_3615', 'addons/featured', 'addons/test_manager',
                'base/collections', 'base/featured',
                'bandwagon/featured_collections', 'base/addon_5299_gcal']

    def setUp(self):
        super(TestAddonManager, self).setUp()
        core.set_user(None)
        self.addon = Addon.objects.get(pk=3615)

    def test_managers_public(self):
        assert self.addon in Addon.objects.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_unlisted(self):
        self.make_addon_unlisted(self.addon)
        assert self.addon in Addon.objects.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_unlisted_deleted(self):
        self.make_addon_unlisted(self.addon)
        self.addon.update(status=amo.STATUS_DELETED)
        assert self.addon not in Addon.objects.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert self.addon not in Addon.objects.all()
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
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert q.count() == 3
        assert Addon.objects.listed(amo.FIREFOX, amo.STATUS_PUBLIC,
                                    amo.STATUS_NOMINATED).count() == 4

        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        assert q.count() == 3

    def test_public(self):
        for a in Addon.objects.public():
            assert a.status == amo.STATUS_PUBLIC

    def test_valid(self):
        addon = Addon.objects.get(pk=5299)
        addon.update(disabled_by_user=True)
        objs = Addon.objects.valid()

        for addon in objs:
            assert addon.status in amo.VALID_ADDON_STATUSES
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

        # Addon shouldn't be listed in collection.addons if it's deleted.

        # Unlisted.
        self.make_addon_unlisted(self.addon)
        collection = Collection.objects.get(pk=collection.pk)
        assert collection.addons.get() == self.addon

        # Deleted and unlisted.
        self.addon.update(status=amo.STATUS_DELETED)
        collection = Collection.objects.get(pk=collection.pk)
        assert collection.addons.count() == 0

        # Only deleted.
        self.make_addon_listed(self.addon)
        collection = Collection.objects.get(pk=collection.pk)
        assert collection.addons.count() == 0

    def test_no_filter_for_relations(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        version = self.addon.versions.first()
        assert version.addon == self.addon

        # Deleted or unlisted, version.addon should still work.

        # Unlisted.
        self.make_addon_unlisted(self.addon)
        version = Version.objects.get(pk=version.pk)  # Reload from db.
        assert version.addon == self.addon

        # Deleted and unlisted.
        self.addon.update(status=amo.STATUS_DELETED)
        version = Version.objects.get(pk=version.pk)  # Reload from db.
        assert version.addon == self.addon

        # Only deleted.
        self.make_addon_listed(self.addon)
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
                'addons/denied',
                'bandwagon/featured_collections']

    def setUp(self):
        super(TestAddonModels, self).setUp()
        TranslationSequence.objects.create(id=99243)
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

    def test_latest_unlisted_version(self):
        addon = Addon.objects.get(pk=3615)
        an_unlisted_version = version_factory(
            addon=addon, version='3.0', channel=amo.RELEASE_CHANNEL_UNLISTED)
        an_unlisted_version.update(created=self.days_ago(2))
        a_newer_unlisted_version = version_factory(
            addon=addon, version='4.0', channel=amo.RELEASE_CHANNEL_UNLISTED)
        a_newer_unlisted_version.update(created=self.days_ago(1))
        version_factory(
            addon=addon, version='5.0', channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_DISABLED})
        assert addon.latest_unlisted_version == a_newer_unlisted_version

        # Make sure the property is cached.
        an_even_newer_unlisted_version = version_factory(
            addon=addon, version='6.0', channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert addon.latest_unlisted_version == a_newer_unlisted_version

        # Make sure it can be deleted to reset it.
        del addon.latest_unlisted_version
        assert addon.latest_unlisted_version == an_even_newer_unlisted_version

        # Make sure it's writeable.
        addon.latest_unlisted_version = an_unlisted_version
        assert addon.latest_unlisted_version == an_unlisted_version

    def test_find_latest_version(self):
        """
        Tests that we get the latest version of an addon.
        """
        addon = Addon.objects.get(pk=3615)
        addon.current_version.update(created=self.days_ago(2))
        new_version = version_factory(addon=addon, version='2.0')
        new_version.update(created=self.days_ago(1))
        assert addon.find_latest_version(None) == new_version
        another_new_version = version_factory(
            addon=addon, version='3.0', channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert addon.find_latest_version(None) == another_new_version

    def test_find_latest_version_different_channel(self):
        addon = Addon.objects.get(pk=3615)
        addon.current_version.update(created=self.days_ago(2))
        new_version = version_factory(addon=addon, version='2.0')
        new_version.update(created=self.days_ago(1))
        unlisted_version = version_factory(
            addon=addon, version='3.0', channel=amo.RELEASE_CHANNEL_UNLISTED)

        assert (
            addon.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED) ==
            new_version)
        assert (
            addon.find_latest_version(channel=amo.RELEASE_CHANNEL_UNLISTED) ==
            unlisted_version)

    def test_find_latest_version_no_version(self):
        Addon.objects.filter(pk=3723).update(_current_version=None)
        Version.objects.filter(addon=3723).delete()
        addon = Addon.objects.get(pk=3723)
        assert addon.find_latest_version(None) is None

    def test_find_latest_version_ignore_disabled(self):
        addon = Addon.objects.get(pk=3615)

        v1 = version_factory(addon=addon, version='1.0')
        v1.update(created=self.days_ago(1))
        assert addon.find_latest_version(None).id == v1.id

        version_factory(addon=addon, version='2.0',
                        file_kw={'status': amo.STATUS_DISABLED})
        # Still should be v1
        assert addon.find_latest_version(None).id == v1.id

    def test_find_latest_version_dont_exclude_anything(self):
        addon = Addon.objects.get(pk=3615)

        v1 = version_factory(addon=addon, version='1.0')
        v1.update(created=self.days_ago(2))

        assert addon.find_latest_version(None, exclude=()).id == v1.id

        v2 = version_factory(addon=addon, version='2.0',
                             file_kw={'status': amo.STATUS_DISABLED})
        v2.update(created=self.days_ago(1))

        # Should be v2 since we don't exclude anything.
        assert addon.find_latest_version(None, exclude=()).id == v2.id

    def test_find_latest_version_dont_exclude_anything_with_channel(self):
        addon = Addon.objects.get(pk=3615)

        v1 = version_factory(addon=addon, version='1.0')
        v1.update(created=self.days_ago(3))

        assert addon.find_latest_version(
            amo.RELEASE_CHANNEL_LISTED, exclude=()).id == v1.id

        v2 = version_factory(addon=addon, version='2.0',
                             file_kw={'status': amo.STATUS_DISABLED})
        v2.update(created=self.days_ago(1))

        version_factory(
            addon=addon, version='4.0', channel=amo.RELEASE_CHANNEL_UNLISTED)

        # Should be v2 since we don't exclude anything, but do have a channel
        # set to listed, and version 4.0 is unlisted.
        assert addon.find_latest_version(
            amo.RELEASE_CHANNEL_LISTED, exclude=()).id == v2.id

    def test_current_version_unsaved(self):
        addon = Addon()
        addon._current_version = Version()
        assert addon.current_version is None

    def test_find_latest_version_unsaved(self):
        addon = Addon()
        assert addon.find_latest_version(None) is None

    def test_transformer(self):
        author = UserProfile.objects.get(pk=55021)
        new_author = AddonUser.objects.create(
            addon_id=3615, user=UserProfile.objects.create(username='abda'),
            listed=True).user

        addon = Addon.objects.get(pk=3615)

        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            assert addon.current_version
            # Use list() so that we evaluate a queryset in case the
            # transformer didn't attach the list directly
            assert [u.pk for u in addon.listed_authors] == [
                author.pk, new_author.pk]

    def _delete(self, addon_id):
        """Test deleting add-ons."""
        core.set_user(UserProfile.objects.last())
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
            'Addon id {0} with GUID {1} has been deleted'.format(
                addon_id, guid))

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

    @patch('olympia.addons.tasks.Preview.delete_preview_files')
    @patch('olympia.versions.tasks.VersionPreview.delete_preview_files')
    def test_delete_deletes_preview_files(self, dpf_vesions_mock,
                                          dpf_addons_mock):
        addon = addon_factory()
        addon_preview = Preview.objects.create(addon=addon)
        version_preview = VersionPreview.objects.create(
            version=addon.current_version)
        addon.delete()
        dpf_addons_mock.assert_called_with(
            sender=None, instance=addon_preview)
        dpf_vesions_mock.assert_called_with(
            sender=None, instance=version_preview)

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
        addon = Addon.objects.get(pk=3615)
        addon.current_version.delete(hard=True)
        # The addon status will have been changed when we deleted the version,
        # and the instance should be the same, so we shouldn't need to reload.
        assert addon.status == amo.STATUS_NULL
        addon.delete(None)
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

    def test_delete_disabled_addon_is_added_to_deniedguids(self):
        addon = Addon.unfiltered.get(pk=3615)
        addon.update(status=amo.STATUS_DISABLED)
        self._delete(3615)
        assert DeniedGuid.objects.filter(guid=addon.guid).exists()

    def test_delete_disabled_addon_when_guid_is_already_in_deniedguids(self):
        addon = Addon.unfiltered.get(pk=3615)
        DeniedGuid.objects.create(guid=addon.guid)
        addon.update(status=amo.STATUS_DISABLED)
        self._delete(3615)
        assert DeniedGuid.objects.filter(guid=addon.guid).exists()

    def test_delete_unknown_type(self):
        """
        Test making sure deleting add-ons with an unknown type, like old
        webapps from Marketplace that are somehow still around, is possible."""
        addon = Addon.objects.get(pk=3615)
        addon.update(type=11)
        self._delete(3615)

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
        1. Test for an icon that is set.
        2. Test for an icon that is set, with an icon hash
        3. Test for default THEME icon.
        4. Test for default non-THEME icon.
        """
        addon = Addon.objects.get(pk=3615)
        assert addon.icon_url.endswith('/3/3615-32.png?modified=1275037317')

        addon.icon_hash = 'somehash'
        assert addon.icon_url.endswith('/3/3615-32.png?modified=somehash')

        addon = Addon.objects.get(pk=6704)
        addon.icon_type = None
        assert addon.icon_url.endswith('/icons/default-theme.png'), (
            'No match for %s' % addon.icon_url)

        addon = Addon.objects.get(pk=3615)
        addon.icon_type = None
        assert addon.icon_url.endswith('icons/default-32.png')

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

        a.status = amo.STATUS_NOMINATED
        assert a.is_unreviewed(), 'pending add-on: is_unreviewed=True'

    def test_is_public(self):
        # Public add-on.
        addon = Addon.objects.get(pk=3615)
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.is_public()

        # Should be public by status, but since it's disabled add-on it's not.
        addon.disabled_by_user = True
        assert not addon.is_public()

    def test_is_restart_required(self):
        addon = Addon.objects.get(pk=3615)
        file_ = addon.current_version.all_files[0]
        assert not file_.is_restart_required
        assert not addon.is_restart_required

        file_.update(is_restart_required=True)
        assert Addon.objects.get(pk=3615).is_restart_required

        addon.versions.all().delete()
        addon._current_version = None
        assert not addon.is_restart_required

    def test_is_featured(self):
        """Test if an add-on is globally featured"""
        a = Addon.objects.get(pk=1003)
        assert a.is_featured(amo.FIREFOX, 'en-US'), (
            'globally featured add-on not recognized')

    def test_get_featured_by_app(self):
        addon = Addon.objects.get(pk=1003)
        featured_coll = addon.collections.get().featuredcollection_set.get()
        assert featured_coll.locale is None
        # Get the applications this addon is featured for.
        assert addon.get_featured_by_app() == {amo.FIREFOX.id: {None}}

        featured_coll.update(locale='fr')
        # Check the locale works.
        assert addon.get_featured_by_app() == {amo.FIREFOX.id: {'fr'}}

        pt_coll = collection_factory()
        pt_coll.add_addon(addon)
        FeaturedCollection.objects.create(collection=pt_coll,
                                          application=amo.FIREFOX.id,
                                          locale='pt-PT')
        # Add another featured collection for the same application.
        assert addon.get_featured_by_app() == {amo.FIREFOX.id: {'fr', 'pt-PT'}}

        mobile_coll = collection_factory()
        mobile_coll.add_addon(addon)
        FeaturedCollection.objects.create(collection=mobile_coll,
                                          application=amo.ANDROID.id,
                                          locale='pt-PT')
        # Add a featured collection for the a different application.
        assert addon.get_featured_by_app() == {
            amo.FIREFOX.id: {'fr', 'pt-PT'},
            amo.ANDROID.id: {'pt-PT'}}

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

    @patch(
        'olympia.amo.templatetags.jinja_helpers.urlresolvers.get_outgoing_url')
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

    def test_app_categories(self):
        def get_addon():
            return Addon.objects.get(pk=3615)

        # This add-on is already associated with three Firefox categories
        # using fixtures: Bookmarks, Feeds, Social.
        FIREFOX_EXT_CATS = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]
        expected_firefox_cats = [
            FIREFOX_EXT_CATS['bookmarks'],
            FIREFOX_EXT_CATS['feeds-news-blogging'],
            FIREFOX_EXT_CATS['social-communication']
        ]

        addon = get_addon()
        assert set(addon.all_categories) == set(expected_firefox_cats)
        assert addon.app_categories == {amo.FIREFOX: expected_firefox_cats}

        # Let's add a thunderbird category.
        thunderbird_static_cat = (
            CATEGORIES[amo.THUNDERBIRD.id][amo.ADDON_EXTENSION]['tags'])
        tb_category = Category.from_static_category(thunderbird_static_cat)
        tb_category.save()
        AddonCategory.objects.create(addon=addon, category=tb_category)

        # Reload the addon to get a fresh, uncached categories list.
        addon = get_addon()

        # Test that the thunderbird category was added correctly.
        assert set(addon.all_categories) == set(
            expected_firefox_cats + [thunderbird_static_cat])
        assert set(addon.app_categories.keys()) == set(
            [amo.FIREFOX, amo.THUNDERBIRD])
        assert set(addon.app_categories[amo.FIREFOX]) == set(
            expected_firefox_cats)
        assert set(addon.app_categories[amo.THUNDERBIRD]) == set(
            [thunderbird_static_cat])

    def test_app_categories_ignore_unknown_cats(self):
        def get_addon():
            return Addon.objects.get(pk=3615)

        # This add-on is already associated with three Firefox categories
        # using fixtures: Bookmarks, Feeds, Social.
        FIREFOX_EXT_CATS = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]
        expected_firefox_cats = [
            FIREFOX_EXT_CATS['bookmarks'],
            FIREFOX_EXT_CATS['feeds-news-blogging'],
            FIREFOX_EXT_CATS['social-communication']
        ]

        addon = get_addon()
        assert set(addon.all_categories) == set(expected_firefox_cats)
        assert addon.app_categories == {amo.FIREFOX: expected_firefox_cats}

        # Associate this add-on with a couple more categories, including
        # one that does not exist in the constants.
        unknown_cat = Category.objects.create(
            application=amo.SUNBIRD.id, id=123456, type=amo.ADDON_EXTENSION,
            db_name='Sunny D')
        AddonCategory.objects.create(addon=addon, category=unknown_cat)
        thunderbird_static_cat = (
            CATEGORIES[amo.THUNDERBIRD.id][amo.ADDON_EXTENSION]['appearance'])
        tb_category = Category.from_static_category(thunderbird_static_cat)
        tb_category.save()
        AddonCategory.objects.create(addon=addon, category=tb_category)

        # Reload the addon to get a fresh, uncached categories list.
        addon = get_addon()

        # The sunbird category should not be present since it does not match
        # an existing static category, thunderbird one should have been added.
        assert set(addon.all_categories) == set(
            expected_firefox_cats + [thunderbird_static_cat])
        assert set(addon.app_categories.keys()) == set(
            [amo.FIREFOX, amo.THUNDERBIRD])
        assert set(addon.app_categories[amo.FIREFOX]) == set(
            expected_firefox_cats)
        assert set(addon.app_categories[amo.THUNDERBIRD]) == set(
            [thunderbird_static_cat])

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=999)
        version = addon.current_version
        new_rating = Rating(version=version, user=u, rating=2, body='hello',
                            addon=addon)
        new_rating.save()
        new_reply = Rating(version=version, user=addon.authors.all()[0],
                           addon=addon, reply_to=new_rating,
                           rating=2, body='my reply')
        new_reply.save()

        review_list = [rating.pk for rating in addon.ratings]

        assert new_rating.pk in review_list, (
            'Original review must show up in review list.')
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.')

    def test_update_logs(self):
        addon = Addon.objects.get(id=3615)
        core.set_user(UserProfile.objects.all()[0])
        addon.versions.all().delete()

        entries = ActivityLog.objects.all()
        assert entries[0].action == amo.LOG.CHANGE_STATUS.id

    def setup_files(self, status):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=status, version=version)
        return addon, version

    def test_no_change_disabled_user(self):
        addon, version = self.setup_files(amo.STATUS_AWAITING_REVIEW)
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

    def test_removing_public(self):
        addon, version = self.setup_files(amo.STATUS_AWAITING_REVIEW)
        addon.update(status=amo.STATUS_PUBLIC)
        version.save()
        assert addon.status == amo.STATUS_NOMINATED

    def test_can_request_review_no_files(self):
        addon = Addon.objects.get(pk=3615)
        addon.versions.all()[0].files.all().delete()
        assert addon.can_request_review() is False

    def test_can_request_review_rejected(self):
        addon = Addon.objects.get(pk=3615)
        latest_version = addon.find_latest_version(amo.RELEASE_CHANNEL_LISTED)
        latest_version.files.update(status=amo.STATUS_DISABLED)
        assert addon.can_request_review() is False

    def check_can_request_review(self, status, expected, extra_update_kw=None):
        if extra_update_kw is None:
            extra_update_kw = {}
        addon = Addon.objects.get(pk=3615)
        changes = {'status': status, 'disabled_by_user': False}
        changes.update(**extra_update_kw)
        addon.update(**changes)
        assert addon.can_request_review() == expected

    def test_can_request_review_null(self):
        self.check_can_request_review(amo.STATUS_NULL, True)

    def test_can_request_review_null_disabled(self):
        self.check_can_request_review(
            amo.STATUS_NULL, False, extra_update_kw={'disabled_by_user': True})

    def test_can_request_review_nominated(self):
        self.check_can_request_review(amo.STATUS_NOMINATED, False)

    def test_can_request_review_public(self):
        self.check_can_request_review(amo.STATUS_PUBLIC, False)

    def test_can_request_review_disabled(self):
        self.check_can_request_review(amo.STATUS_DISABLED, False)

    def test_can_request_review_deleted(self):
        self.check_can_request_review(amo.STATUS_DELETED, False)

    def test_none_homepage(self):
        # There was an odd error when a translation was set to None.
        Addon.objects.create(homepage=None, type=amo.ADDON_EXTENSION)

    def test_slug_isdigit(self):
        a = Addon.objects.create(type=1, name='xx', slug='123')
        assert a.slug == '123~'

        a.slug = '44'
        a.save()
        assert a.slug == '44~'

    def test_slug_isdenied(self):
        # When an addon is uploaded, it doesn't use the form validation,
        # so we'll just mangle the slug if its denied.
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
            core.set_user(user)
            self.delete()
            assert 'DELETED BY: 55021' in mail.outbox[0].body
        finally:
            core.set_user(None)

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

    def test_listed_has_complete_metadata_no_categories(self):
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Confirm complete already.

        AddonCategory.objects.filter(addon=addon).delete()
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        assert addon.has_complete_metadata(has_listed_versions=False)

    def test_listed_has_complete_metadata_no_summary(self):
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Confirm complete already.

        delete_translation(addon, 'summary')
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        assert addon.has_complete_metadata(
            has_listed_versions=False)

    def test_listed_has_complete_metadata_no_license(self):
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Confirm complete already.

        addon.current_version.update(license=None)
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        assert addon.has_complete_metadata(
            has_listed_versions=False)

    def test_unlisted_has_complete_metadata(self):
        addon = Addon.objects.get(id=3615)
        self.make_addon_unlisted(addon)
        assert addon.has_complete_metadata()  # Confirm complete already.

        # Clear everything
        addon.versions.update(license=None)
        AddonCategory.objects.filter(addon=addon).delete()
        delete_translation(addon, 'summary')
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Still complete
        assert not addon.has_complete_metadata(has_listed_versions=True)

    def test_can_review(self):
        user = AnonymousUser()
        addon = Addon.objects.get(id=3615)
        assert addon.can_review(user)

        user = addon.addonuser_set.all()[0].user
        assert not addon.can_review(user)

        user = UserProfile.objects.get(pk=2519)
        assert addon.can_review(user)

    def test_has_author(self):
        addon = Addon.objects.get(id=3615)
        user = addon.addonuser_set.all()[0].user
        assert addon.has_author(user)

        user = UserProfile.objects.get(pk=2519)
        assert not addon.has_author(user)

    def test_auto_approval_disabled_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_disabled is None
        # Flag present, value is False (default): False.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.auto_approval_disabled is False
        assert addon.auto_approval_disabled is False
        # Flag present, value is True: True.
        flags.update(auto_approval_disabled=True)
        assert addon.auto_approval_disabled is True

    def test_needs_admin_code_review_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.needs_admin_code_review is None
        # Flag present, value is False (default): False.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.needs_admin_code_review is False
        assert addon.needs_admin_code_review is False
        # Flag present, value is True: True.
        flags.update(needs_admin_code_review=True)
        assert addon.needs_admin_code_review is True

    def test_needs_admin_content_review_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.needs_admin_content_review is None
        # Flag present, value is False (default): False.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.needs_admin_content_review is False
        assert addon.needs_admin_content_review is False
        # Flag present, value is True: True.
        flags.update(needs_admin_content_review=True)
        assert addon.needs_admin_content_review is True

    def test_needs_admin_theme_review_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.needs_admin_theme_review is None
        # Flag present, value is False (default): False.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.needs_admin_theme_review is False
        assert addon.needs_admin_theme_review is False
        # Flag present, value is True: True.
        flags.update(needs_admin_theme_review=True)
        assert addon.needs_admin_theme_review is True

    def test_pending_info_request_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.pending_info_request is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.pending_info_request is None
        assert addon.pending_info_request is None
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(pending_info_request=in_the_past)
        assert addon.pending_info_request == in_the_past

    def test_expired_info_request_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.expired_info_request is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.pending_info_request is None
        assert addon.expired_info_request is None
        # Flag present, value is a date in the past.
        in_the_past = self.days_ago(1)
        flags.update(pending_info_request=in_the_past)
        assert addon.expired_info_request

        # Flag present, value is a date in the future.
        in_the_future = datetime.now() + timedelta(days=2)
        flags.update(pending_info_request=in_the_future)
        assert not addon.expired_info_request


class TestShouldRedirectToSubmitFlow(TestCase):
    fixtures = ['base/addon_3615']

    def test_no_versions_doesnt_redirect(self):
        addon = Addon.objects.get(id=3615)
        assert not addon.should_redirect_to_submit_flow()

        # Now break addon.
        delete_translation(addon, 'summary')
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        addon.update(status=amo.STATUS_NULL)
        assert addon.should_redirect_to_submit_flow()

        for ver in addon.versions.all():
            ver.delete()
        assert not addon.should_redirect_to_submit_flow()

    def test_disabled_versions_doesnt_redirect(self):
        addon = Addon.objects.get(id=3615)
        assert not addon.should_redirect_to_submit_flow()

        # Now break addon.
        delete_translation(addon, 'summary')
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        addon.update(status=amo.STATUS_NULL)
        assert addon.should_redirect_to_submit_flow()

        for ver in addon.versions.all():
            for file_ in ver.all_files:
                file_.update(status=amo.STATUS_DISABLED)
        assert not addon.should_redirect_to_submit_flow()

    def test_only_null_redirects(self):
        addon = Addon.objects.get(id=3615)
        assert not addon.should_redirect_to_submit_flow()

        # Now break addon.
        delete_translation(addon, 'summary')
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()

        status_exc_null = dict(amo.STATUS_CHOICES_ADDON)
        status_exc_null.pop(amo.STATUS_NULL)
        for status in status_exc_null:
            assert not addon.should_redirect_to_submit_flow()
        addon.update(status=amo.STATUS_NULL)
        assert addon.should_redirect_to_submit_flow()


class TestHasListedAndUnlistedVersions(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        latest_version.delete(hard=True)
        assert self.addon.versions.count() == 0

    def test_no_versions(self):
        assert not self.addon.has_listed_versions()
        assert not self.addon.has_unlisted_versions()

    def test_listed_version(self):
        version_factory(channel=amo.RELEASE_CHANNEL_LISTED, addon=self.addon)
        assert self.addon.has_listed_versions()
        assert not self.addon.has_unlisted_versions()

    def test_unlisted_version(self):
        version_factory(channel=amo.RELEASE_CHANNEL_UNLISTED, addon=self.addon)
        assert not self.addon.has_listed_versions()
        assert self.addon.has_unlisted_versions()

    def test_unlisted_and_listed_versions(self):
        version_factory(channel=amo.RELEASE_CHANNEL_LISTED, addon=self.addon)
        version_factory(channel=amo.RELEASE_CHANNEL_UNLISTED, addon=self.addon)
        assert self.addon.has_listed_versions()
        assert self.addon.has_unlisted_versions()


class TestAddonNomination(TestCase):
    fixtures = ['base/addon_3615']

    def test_set_nomination(self):
        a = Addon.objects.get(id=3615)
        a.update(status=amo.STATUS_NULL)
        a.versions.latest().update(nomination=None)
        a.update(status=amo.STATUS_NOMINATED)
        assert a.versions.latest().nomination

    def test_new_version_inherits_nomination(self):
        a = Addon.objects.get(id=3615)
        ver = 10
        a.update(status=amo.STATUS_NOMINATED)
        old_ver = a.versions.latest()
        v = Version.objects.create(addon=a, version=str(ver))
        assert v.nomination == old_ver.nomination
        ver += 1

    def test_lone_version_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        Version.objects.all().delete()
        v = Version.objects.create(addon=a, version='1.0')
        assert v.nomination is None

    def test_reviewed_addon_does_not_inherit_nomination(self):
        a = Addon.objects.get(id=3615)
        ver = 10
        for st in (amo.STATUS_PUBLIC, amo.STATUS_NULL):
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

    def setup_nomination(self, addon_status=amo.STATUS_NOMINATED,
                         file_status=amo.STATUS_AWAITING_REVIEW):
        addon = Addon.objects.create()
        version = Version.objects.create(addon=addon)
        File.objects.create(status=file_status, version=version)
        # Cheating date to make sure we don't have a date on the same second
        # the code we test is running.
        past = self.days_ago(1)
        version.update(nomination=past, created=past, modified=past)
        addon.update(status=addon_status)
        nomination = addon.versions.latest().nomination
        assert nomination
        return addon, nomination

    def test_new_version_of_under_review_addon_does_not_reset_nomination(self):
        addon, nomination = self.setup_nomination()
        version = Version.objects.create(addon=addon, version='0.2')
        File.objects.create(status=amo.STATUS_AWAITING_REVIEW, version=version)
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
        File.objects.create(status=amo.STATUS_AWAITING_REVIEW, version=version)
        assert addon.versions.latest().nomination == nomination
        # Adding a new unreviewed version.
        version = Version.objects.create(addon=addon, version="0.3")
        File.objects.create(status=amo.STATUS_AWAITING_REVIEW, version=version)
        assert addon.versions.latest().nomination == nomination

    def check_nomination_reset_with_new_version(self, addon, nomination):
        version = Version.objects.create(addon=addon, version="0.2")
        assert version.nomination is None
        File.objects.create(status=amo.STATUS_AWAITING_REVIEW, version=version)
        assert addon.versions.latest().nomination != nomination

    def test_new_version_of_approved_addon_should_reset_nomination(self):
        addon, nomination = self.setup_nomination(
            addon_status=amo.STATUS_PUBLIC, file_status=amo.STATUS_PUBLIC)
        # Now create a new version with an attached file, and update status.
        self.check_nomination_reset_with_new_version(addon, nomination)


class TestThemeDelete(TestCase):

    def setUp(self):
        super(TestThemeDelete, self).setUp()
        self.addon = addon_factory(type=amo.ADDON_PERSONA)

        # Taking the creation and modified time back 1 day
        self.addon.update(created=self.days_ago(1), modified=self.days_ago(1))

    def test_remove_theme_update_m_time(self):
        m_time_before = self.addon.modified
        self.addon.delete('enough', 'no reason at all')
        m_time_after = self.addon.modified

        assert m_time_before != m_time_after


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

        # This should not throw any FK errors if all the cascades work.
        addon.delete()
        # Make sure it was actually a hard delete.
        assert not Addon.unfiltered.filter(pk=addon.pk).exists()

    def test_review_delete(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_PUBLIC)

        rating = Rating.objects.create(addon=addon, rating=1, body='foo',
                                       user=UserProfile.objects.create())

        flag = RatingFlag(rating=rating)

        addon.delete()

        assert Addon.unfiltered.filter(pk=addon.pk).exists()
        assert not Rating.objects.filter(pk=rating.pk).exists()
        assert not RatingFlag.objects.filter(pk=flag.pk).exists()

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
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NOMINATED)
        Version.objects.create(addon=addon)
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NULL)

    def test_no_valid_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = Version.objects.create(addon=addon)
        f = File.objects.create(status=amo.STATUS_AWAITING_REVIEW,
                                version=version)
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NOMINATED)
        f.status = amo.STATUS_DISABLED
        f.save()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NULL)

    def test_unlisted_versions_ignored(self):
        addon = addon_factory(status=amo.STATUS_PUBLIC)
        addon.update_status()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_PUBLIC)

        addon.current_version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # update_status will have been called via versions.models.update_status
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NULL)  # No listed versions so now NULL


class TestGetVersion(TestCase):
    fixtures = ['base/addon_3615', ]

    def setUp(self):
        super(TestGetVersion, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def test_public_new_public_version(self):
        new_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_PUBLIC})
        assert self.addon.find_latest_public_listed_version() == new_version

    def test_public_new_unreviewed_version(self):
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        assert self.addon.find_latest_public_listed_version() == self.version

    def test_should_promote_previous_valid_version_if_latest_is_disabled(self):
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        assert self.addon.find_latest_public_listed_version() == self.version

    def test_should_be_listed(self):
        new_version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_PUBLIC})
        assert new_version != self.version
        # Since the new version is unlisted, find_latest_public_listed_version
        # should still find the current one.
        assert self.addon.find_latest_public_listed_version() == self.version


class TestAddonGetURLPath(TestCase):

    def test_get_url_path(self):
        addon = addon_factory(slug='woo')
        assert addon.get_url_path() == '/en-US/firefox/addon/woo/'

    def test_get_url_path_more(self):
        addon = addon_factory(slug='yeah')
        assert addon.get_url_path(more=True) == (
            '/en-US/firefox/addon/yeah/more')

    def test_unlisted_addon_get_url_path(self):
        addon = addon_factory(
            slug='woo', version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        assert addon.get_url_path() == ''


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
        core.set_user(None)

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

    def test_current_version_listed_only(self):
        version = self.addon.current_version
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # The call above should have triggerred update_version().
        assert self.addon.current_version != version
        # new current_version should be version 1.2.1, since 1.2.2 is unlisted.
        assert self.addon.current_version == Version.objects.get(pk=112396)

    def test_firefox_versions(self):
        self.setup_new_version()
        self.addon.update_version()
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
        self.addon.update(_current_version=None, _signal=False)
        assert self.addon.update_version()
        assert self.addon._current_version == (
            self.addon.find_latest_version(None))


class TestCategoryModel(TestCase):

    def test_category_url(self):
        """Every type must have a url path for its categories."""
        for t in amo.ADDON_TYPE.keys():
            if t == amo.ADDON_DICT:
                continue  # Language packs don't have categories.
            cat = Category(type=t, slug='omg')
            assert cat.get_url_path()

    @pytest.mark.needs_locales_compilation
    def test_name_from_constants(self):
        category = Category(
            type=amo.ADDON_EXTENSION, application=amo.FIREFOX.id,
            slug='alerts-updates')
        assert category.name == u'Alerts & Updates'
        with translation.override('fr'):
            assert category.name == u'Alertes et mises à jour'

    def test_name_fallback_to_db(self):
        category = Category.objects.create(
            type=amo.ADDON_EXTENSION, application=amo.FIREFOX.id,
            slug='this-cat-does-not-exist', db_name=u'ALAAAAAAARM')

        assert category.name == u'ALAAAAAAARM'
        with translation.override('fr'):
            assert category.name == u'ALAAAAAAARM'


class TestPersonaModel(TestCase):
    fixtures = ['addons/persona']

    def setUp(self):
        super(TestPersonaModel, self).setUp()
        self.addon = Addon.objects.get(id=15663)
        self.persona = self.addon.persona
        self.persona.header = 'header.png'
        self.persona.footer = 'footer.png'
        self.persona.popularity = 12345
        self.persona.save()

    def _expected_url(self, img_name, modified_suffix):
        return '/15663/%s?modified=%s' % (img_name, modified_suffix)

    def test_image_urls(self):
        self.persona.persona_id = 0
        self.persona.checksum = 'fakehash'
        self.persona.save()
        modified = 'fakehash'
        assert self.persona.thumb_url.endswith(
            self._expected_url('preview.png', modified))
        assert self.persona.icon_url.endswith(
            self._expected_url('icon.png', modified))
        assert self.persona.preview_url.endswith(
            self._expected_url('preview.png', modified))
        assert self.persona.header_url.endswith(
            self._expected_url('header.png', modified))
        assert self.persona.footer_url.endswith(
            self._expected_url('footer.png', modified))

    def test_image_urls_no_checksum(self):
        # AMO-uploaded themes have `persona_id=0`.
        self.persona.persona_id = 0
        self.persona.save()
        modified = int(time.mktime(self.persona.addon.modified.timetuple()))
        assert self.persona.thumb_url.endswith(
            self._expected_url('preview.png', modified))
        assert self.persona.icon_url.endswith(
            self._expected_url('icon.png', modified))
        assert self.persona.preview_url.endswith(
            self._expected_url('preview.png', modified))
        assert self.persona.header_url.endswith(
            self._expected_url('header.png', modified))
        assert self.persona.footer_url.endswith(
            self._expected_url('footer.png', modified))

    def test_old_image_urls(self):
        self.persona.addon.modified = None
        modified = 0
        assert self.persona.thumb_url.endswith(
            self._expected_url('preview.jpg', modified))
        assert self.persona.icon_url.endswith(
            self._expected_url('preview_small.jpg', modified))
        assert self.persona.preview_url.endswith(
            self._expected_url('preview_large.jpg', modified))
        assert self.persona.header_url.endswith(
            self._expected_url('header.png', modified))
        assert self.persona.footer_url.endswith(
            self._expected_url('footer.png', modified))

    def test_update_url(self):
        with self.settings(LANGUAGE_CODE='fr', LANGUAGE_URL_MAP={}):
            url_ = self.persona.update_url
            assert url_.endswith('/fr/themes/update-check/15663')

    def test_json_data(self):
        self.persona.addon.all_categories = [Category(db_name='Yolo Art')]

        with self.settings(LANGUAGE_CODE='fr',
                           LANGUAGE_URL_MAP={},
                           VAMO_URL='https://vamo',
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

        self.persona.addon.all_categories = [Category(db_name='Yolo Art')]

        with self.settings(LANGUAGE_CODE='fr',
                           LANGUAGE_URL_MAP={},
                           VAMO_URL='https://vamo',
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

    def test_json_data_missing_colors(self):
        self.persona.accentcolor = ''
        self.persona.textcolor = ''
        self.persona.save()

        data = self.persona.theme_data
        assert data['accentcolor'] is None
        assert data['textcolor'] is None

        self.persona.accentcolor = None
        self.persona.textcolor = None
        self.persona.save()

        data = self.persona.theme_data
        assert data['accentcolor'] is None
        assert data['textcolor'] is None

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

    def test_theme_data_with_null_description(self):
        addon = addon_factory(type=amo.ADDON_PERSONA, description=None)
        assert addon.persona.theme_data['description'] is None


class TestPreviewModel(BasePreviewMixin, TestCase):
    fixtures = ['base/previews']

    def get_object(self):
        return Preview.objects.get(pk=24)


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
        core.set_user(u)
        self.platform = amo.PLATFORM_MAC.id
        for version in ('3.0', '3.6.*'):
            AppVersion.objects.create(application=1, version=version)
        self.addCleanup(translation.deactivate)
        self.dummy_parsed_data = {
            'guid': 'guid@xpi',
            'version': '0.1'
        }

    def manifest(self, basename):
        return os.path.join(
            settings.ROOT, 'src', 'olympia', 'devhub', 'tests', 'addons',
            basename)

    def test_denied_guid(self):
        """Add-ons that have been disabled by Mozilla are added toDeniedGuid
        in order to prevent resubmission after deletion """
        DeniedGuid.objects.create(guid='guid@xpi')
        with self.assertRaises(forms.ValidationError) as e:
            parse_addon(self.get_upload('extension.xpi'), user=Mock())
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid(self):
        # Upload addon so we can delete it.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        deleted = Addon.from_upload(self.upload, [self.platform],
                                    parsed_data=parsed_data)
        deleted.update(status=amo.STATUS_PUBLIC)
        deleted.delete()
        assert deleted.guid == 'guid@xpi'

        # Now upload the same add-on again (so same guid).
        with self.assertRaises(forms.ValidationError) as e:
            self.upload = self.get_upload('extension.xpi')
            parse_addon(self.upload, user=Mock())
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid_same_author(self):
        # Upload addon so we can delete it.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        deleted = Addon.from_upload(self.upload, [self.platform],
                                    parsed_data=parsed_data)
        # Claim the add-on.
        AddonUser(addon=deleted, user=UserProfile.objects.get(pk=999)).save()
        deleted.update(status=amo.STATUS_PUBLIC)
        deleted.delete()
        assert deleted.guid == 'guid@xpi'

        # Now upload the same add-on again (so same guid), checking no
        # validationError is raised this time.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(self.upload, [self.platform],
                                  parsed_data=parsed_data)
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
            self.get_upload('extension.xpi'), [self.platform],
            parsed_data=self.dummy_parsed_data)
        deleted2 = Addon.from_upload(
            self.get_upload('alt-rdf.xpi'), [self.platform],
            parsed_data=self.dummy_parsed_data)
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
        self.upload = self.get_upload('search.xml')
        parsed_data = parse_addon(self.upload, user=Mock())
        Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

    def test_xpi_attributes(self):
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(self.upload, [self.platform],
                                  parsed_data=parsed_data)
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
                                  [self.platform],
                                  parsed_data=self.dummy_parsed_data)
        version = addon.versions.get()
        assert version.version == '0.1'
        assert version.files.get().platform == self.platform
        assert version.files.get().status == amo.STATUS_AWAITING_REVIEW

    def test_xpi_for_multiple_platforms(self):
        platforms = [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id]
        addon = Addon.from_upload(self.get_upload('extension.xpi'),
                                  platforms,
                                  parsed_data=self.dummy_parsed_data)
        version = addon.versions.get()
        assert sorted([file_.platform for file_ in version.all_files]) == (
            sorted(platforms))

    def test_search_attributes(self):
        self.upload = self.get_upload('search.xml')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(self.upload, [self.platform],
                                  parsed_data=parsed_data)
        assert addon.name == 'search tool'
        assert addon.guid is None
        assert addon.type == amo.ADDON_SEARCH
        assert addon.status == amo.STATUS_NULL
        assert addon.homepage is None
        assert addon.description is None
        assert addon.slug == 'search-tool'
        assert addon.summary == 'Search Engine for Firefox'

    def test_search_version(self):
        self.upload = self.get_upload('search.xml')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(self.upload,
                                  [self.platform],
                                  parsed_data=parsed_data)
        version = addon.versions.get()
        assert version.version == datetime.now().strftime('%Y%m%d')
        assert version.files.get().platform == amo.PLATFORM_ALL.id
        assert version.files.get().status == amo.STATUS_AWAITING_REVIEW

    def test_no_homepage(self):
        addon = Addon.from_upload(self.get_upload('extension-no-homepage.xpi'),
                                  [self.platform],
                                  parsed_data=self.dummy_parsed_data)
        assert addon.homepage is None

    def test_default_locale(self):
        # Make sure default_locale follows the active translation.
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform],
                                  parsed_data=self.dummy_parsed_data)
        assert addon.default_locale == 'en-US'

        translation.activate('es')
        addon = Addon.from_upload(self.get_upload('search.xml'),
                                  [self.platform],
                                  parsed_data=self.dummy_parsed_data)
        assert addon.default_locale == 'es'

    def test_validation_completes(self):
        upload = self.get_upload('extension.xpi')
        assert not upload.validation_timeout
        addon = Addon.from_upload(
            upload, [self.platform], parsed_data=self.dummy_parsed_data)
        assert not addon.needs_admin_code_review

    def test_validation_timeout(self):
        upload = self.get_upload('extension.xpi')
        validation = json.loads(upload.validation)
        timeout_message = {
            'id': ['validator', 'unexpected_exception', 'validation_timeout'],
        }
        validation['messages'] = [timeout_message] + validation['messages']
        upload.validation = json.dumps(validation)
        assert upload.validation_timeout
        addon = Addon.from_upload(
            upload, [self.platform], parsed_data=self.dummy_parsed_data)
        assert addon.needs_admin_code_review

    def test_webextension_generate_guid(self):
        self.upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

        assert addon.guid is not None
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

        # Uploading the same addon without a id works.
        self.upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        new_addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)
        assert new_addon.guid is not None
        assert new_addon.guid != addon.guid
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

    def test_webextension_reuse_guid(self):
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

        assert addon.guid == '@webextension-guid'

        # Uploading the same addon with pre-existing id fails
        with self.assertRaises(forms.ValidationError) as e:
            self.upload = self.get_upload('webextension.xpi')
            parsed_data = parse_addon(self.upload, user=Mock())
            Addon.from_upload(self.upload, [self.platform],
                              parsed_data=parsed_data)
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_basic_extension_is_marked_as_e10s_unknown(self):
        # extension.xpi does not have multiprocessCompatible set to true, so
        # it's marked as not-compatible.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_UNKNOWN

    def test_extension_is_marked_as_e10s_incompatible(self):
        self.upload = self.get_upload(
            'multiprocess_incompatible_extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_INCOMPATIBLE

    def test_multiprocess_extension_is_marked_as_e10s_compatible(self):
        self.upload = self.get_upload(
            'multiprocess_compatible_extension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_COMPATIBLE

    def test_webextension_is_marked_as_e10s_compatible(self):
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

        assert addon.guid
        feature_compatibility = addon.feature_compatibility
        assert feature_compatibility.pk
        assert feature_compatibility.e10s == amo.E10S_COMPATIBLE_WEBEXTENSION

    def test_webextension_resolve_translations(self):
        self.upload = self.get_upload('notify-link-clicks-i18n.xpi')
        parsed_data = parse_addon(self.upload, user=Mock())
        addon = Addon.from_upload(
            self.upload, [self.platform], parsed_data=parsed_data)

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

    def test_webext_resolve_translations_corrects_locale(self):
        """Make sure we correct invalid `default_locale` values"""
        parsed_data = {
            'default_locale': u'sv',
            'e10s_compatibility': 2,
            'guid': u'notify-link-clicks-i18n@notzilla.org',
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
            [self.platform], parsed_data=parsed_data)

        # Normalized from `sv` to `sv-SE`
        assert addon.default_locale == 'sv-SE'

    def test_webext_resolve_translations_unknown_locale(self):
        """Make sure we use our default language as default
        for invalid locales
        """
        parsed_data = {
            'default_locale': u'xxx',
            'e10s_compatibility': 2,
            'guid': u'notify-link-clicks-i18n@notzilla.org',
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
            [self.platform], parsed_data=parsed_data)

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'


REDIRECT_URL = 'https://outgoing.prod.mozaws.net/v1/'


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


class TestTrackAddonStatusChange(TestCase):

    def create_addon(self, **kwargs):
        return addon_factory(kwargs.pop('status', amo.STATUS_NULL), **kwargs)

    def test_increment_new_status(self):
        with patch('olympia.addons.models.track_addon_status_change') as mock_:
            addon = Addon()
            addon.save()
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


class TestSearchSignals(amo.tests.ESTestCase):

    def setUp(self):
        super(TestSearchSignals, self).setUp()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.empty_index('default')

    def test_no_addons(self):
        assert Addon.search_public().count() == 0

    def test_create(self):
        addon = addon_factory(name='woo')
        self.refresh()
        assert Addon.search_public().count() == 1
        assert Addon.search_public().query(name='woo')[0].id == addon.id

    def test_update(self):
        addon = addon_factory(name='woo')
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
        addon = addon_factory(name='woo')
        self.refresh()
        assert Addon.search_public().count() == 1

        addon.update(disabled_by_user=True)
        self.refresh()

        assert Addon.search_public().count() == 0

    def test_switch_to_unlisted(self):
        """Test that add-ons are removed from search results after being
        switched to unlisted."""
        addon = addon_factory(name='woo')
        self.refresh()
        assert Addon.search_public().count() == 1

        addon.current_version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.refresh()

        assert Addon.search_public().count() == 0

    def test_switch_to_listed(self):
        """Test that add-ons created as unlisted do not appear in search
        results until switched to listed."""
        addon = addon_factory(
            name='woo', version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
            status=amo.STATUS_NULL)
        self.refresh()
        assert Addon.search_public().count() == 0

        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        latest_version.update(channel=amo.RELEASE_CHANNEL_LISTED)
        addon.update(status=amo.STATUS_PUBLIC)
        self.refresh()

        assert Addon.search_public().count() == 1

    def test_delete(self):
        addon = addon_factory(name='woo')
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


class TestAddonApprovalsCounter(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_increment_existing(self):
        assert not AddonApprovalsCounter.objects.filter(
            addon=self.addon).exists()
        AddonApprovalsCounter.increment_for_addon(self.addon)
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1
        self.assertCloseToNow(approval_counter.last_human_review)
        self.assertCloseToNow(approval_counter.last_content_review)
        approval_counter.update(
            last_human_review=self.days_ago(100),
            last_content_review=self.days_ago(100))
        AddonApprovalsCounter.increment_for_addon(self.addon)
        approval_counter.reload()
        assert approval_counter.counter == 2
        self.assertCloseToNow(approval_counter.last_human_review)
        self.assertCloseToNow(approval_counter.last_content_review)

    def test_increment_non_existing(self):
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon, counter=0)
        AddonApprovalsCounter.increment_for_addon(self.addon)
        approval_counter.reload()
        assert approval_counter.counter == 1
        self.assertCloseToNow(approval_counter.last_human_review)
        self.assertCloseToNow(approval_counter.last_content_review)

    def test_reset_existing(self):
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon, counter=42,
            last_content_review=self.days_ago(60),
            last_human_review=self.days_ago(30))
        AddonApprovalsCounter.reset_for_addon(self.addon)
        approval_counter.reload()
        assert approval_counter.counter == 0
        # Dates were not touched.
        self.assertCloseToNow(
            approval_counter.last_human_review, now=self.days_ago(30))
        self.assertCloseToNow(
            approval_counter.last_content_review, now=self.days_ago(60))

    def test_reset_non_existing(self):
        assert not AddonApprovalsCounter.objects.filter(
            addon=self.addon).exists()
        AddonApprovalsCounter.reset_for_addon(self.addon)
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 0

    def test_approve_content_non_existing(self):
        assert not AddonApprovalsCounter.objects.filter(
            addon=self.addon).exists()
        AddonApprovalsCounter.approve_content_for_addon(self.addon)
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 0
        assert approval_counter.last_human_review is None
        self.assertCloseToNow(approval_counter.last_content_review)

    def test_approve_content_existing(self):
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon, counter=42,
            last_content_review=self.days_ago(367),
            last_human_review=self.days_ago(10))
        AddonApprovalsCounter.approve_content_for_addon(self.addon)
        approval_counter.reload()
        # This was updated to now.
        self.assertCloseToNow(approval_counter.last_content_review)
        # Those fields were not touched.
        assert approval_counter.counter == 42
        self.assertCloseToNow(
            approval_counter.last_human_review, now=self.days_ago(10))


class TestMigratedLWTModel(TestCase):
    def setUp(self):
        self.lwt = addon_factory(type=amo.ADDON_PERSONA)
        self.lwt.persona.persona_id = 999
        self.lwt.persona.save()
        self.static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        MigratedLWT.objects.create(
            lightweight_theme=self.lwt,
            static_theme=self.static_theme)

    def test_addon_id_lookup(self):
        match = MigratedLWT.objects.get(lightweight_theme=self.lwt)
        assert match.static_theme == self.static_theme
        match = MigratedLWT.objects.get(lightweight_theme_id=self.lwt.id)
        assert match.static_theme == self.static_theme

    def test_getpersonas_id_lookup(self):
        match = MigratedLWT.objects.get(getpersonas_id=999)
        assert match.static_theme == self.static_theme
