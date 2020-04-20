# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from django import forms
from django.conf import settings
from django.core import mail
from django.utils import translation
from olympia import amo, core
from olympia.activity.models import ActivityLog, AddonLog
from olympia.addons import models as addons_models
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonCategory, AddonReviewerFlags, AddonUser,
    AppSupport, Category, DeniedGuid, DeniedSlug, FrozenAddon, MigratedLWT,
    Preview, ReusedGUID, track_addon_status_change)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase, addon_factory, user_factory, version_factory)
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.blocklist.models import Block, BlocklistSubmission
from olympia.constants.categories import CATEGORIES
from olympia.devhub.models import RssKey
from olympia.discovery.models import DiscoveryItem
from olympia.files.models import File
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import Extractor, parse_addon
from olympia.git.models import AddonGitExtraction
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

    def test_name_only_has_invalid_slug_chars(self):
        # Create an addon and save it to have an id.
        a = Addon.objects.create()
        # Give the Addon a name that would slugify would reduce to ''.
        a.slug = ''
        a.name = '%$#'
        a.clean_slug()

        # Slugs that are generated from add-ons without an name use
        # uuid without the node bit so have the length 20.
        assert len(a.slug) == 20


class TestAddonManager(TestCase):
    fixtures = ['base/appversion', 'base/users', 'base/addon_3615',
                'addons/test_manager', 'base/collections', 'base/featured',
                'base/addon_5299_gcal']

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

    def test_listed(self):
        # We need this for the fixtures, but it messes up the tests.
        self.addon.update(disabled_by_user=True)
        # Now continue as normal.
        Addon.objects.filter(id=5299).update(disabled_by_user=True)
        q = Addon.objects.listed(amo.FIREFOX, amo.STATUS_APPROVED)
        assert len(q.all()) == 3

        # Pick one of the listed addons.
        addon = Addon.objects.get(pk=2464)
        assert addon in q.all()

        # Disabling hides it.
        addon.disabled_by_user = True
        addon.save()

        # Should be 2 now, since the one is now disabled.
        assert q.count() == 2

        # If we search for public or unreviewed we find it.
        addon.disabled_by_user = False
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert q.count() == 2
        assert Addon.objects.listed(amo.FIREFOX, amo.STATUS_APPROVED,
                                    amo.STATUS_NOMINATED).count() == 3

        # Can't find it without a file.
        addon.versions.get().files.get().delete()
        assert q.count() == 2

    def test_public(self):
        for a in Addon.objects.public():
            assert a.status == amo.STATUS_APPROVED

    def test_valid(self):
        addon = Addon.objects.get(pk=5299)
        addon.update(disabled_by_user=True)
        objs = Addon.objects.valid()

        for addon in objs:
            assert addon.status in amo.VALID_ADDON_STATUSES
            assert not addon.disabled_by_user

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
                'base/users',
                'base/addon_5299_gcal',
                'base/addon_3615',
                'base/addon_3723_listed',
                'base/addon_4594_a9',
                'base/addon_4664_twitterbar',
                'addons/invalid_latest_version',
                'addons/denied']

    def setUp(self):
        super(TestAddonModels, self).setUp()
        TranslationSequence.objects.create(id=99243)

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

    @patch('olympia.files.tasks.hide_disabled_files')
    def test_delete_hides_files(self, hide_disabled_files_mock):
        addon = addon_factory()
        addon.delete()
        hide_disabled_files_mock.delay.assert_called_with(
            addon_id=addon.id)

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

    def test_delete_send_delete_email_false(self):
        addon_a = addon_factory()
        addon_b = addon_factory()

        addon_a.delete()
        assert len(mail.outbox) == 1  # email sent for addon_a
        addon_b.delete(send_delete_email=False)
        assert len(mail.outbox) == 1  # no additional email sent for addon_b

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

    def test_soft_delete_disables_files_and_soft_deletes_versions(self):
        addon = Addon.unfiltered.get(pk=3615)
        files = File.objects.filter(version__addon=addon)
        versions = Version.unfiltered.filter(addon=addon)
        assert versions
        assert files
        for file_ in files:
            assert file_.status != amo.STATUS_DISABLED
        for version in versions:
            assert not version.deleted

        self._delete(3615)

        files = File.objects.filter(version__addon=addon)
        versions = Version.unfiltered.filter(addon=addon)
        assert versions
        assert files
        for file_ in files:
            assert file_.status == amo.STATUS_DISABLED
        for version in versions:
            assert version.deleted

    def test_force_disable(self):
        addon = Addon.unfiltered.get(pk=3615)
        assert addon.status != amo.STATUS_DISABLED
        files = File.objects.filter(version__addon=addon)
        assert files
        for file_ in files:
            assert file_.status != amo.STATUS_DISABLED

        addon.force_disable()

        assert addon.status == amo.STATUS_DISABLED
        files = File.objects.filter(version__addon=addon)
        assert files
        for file_ in files:
            assert file_.status == amo.STATUS_DISABLED

    def test_incompatible_latest_apps(self):
        a = Addon.objects.get(pk=3615)
        assert a.incompatible_latest_apps() == []

        av = ApplicationsVersions.objects.get(pk=47881)
        av.max = AppVersion.objects.get(pk=97)  # Firefox 2.0
        av.save()

        a = Addon.objects.get(pk=3615)
        assert a.incompatible_latest_apps() == [
            (amo.FIREFOX, AppVersion.objects.get(version_int=4000000200100))
        ]

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
        assert addon.get_icon_url(32).endswith(
            '/3/3615-32.png?modified=1275037317')

        addon.icon_hash = 'somehash'
        assert addon.get_icon_url(32).endswith(
            '/3/3615-32.png?modified=somehash')

        addon = Addon.objects.get(pk=3615)
        addon.icon_type = None
        assert addon.get_icon_url(32).endswith('icons/default-32.png')

    def test_icon_url_default(self):
        a = Addon.objects.get(pk=3615)
        a.update(icon_type='')
        default = 'icons/default-32.png'
        assert a.get_icon_url(32).endswith(default)
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
        assert addon.status == amo.STATUS_APPROVED
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
        assert sorted(addon.all_categories) == expected_firefox_cats
        assert addon.app_categories == {'firefox': expected_firefox_cats}

        # Let's add a ANDROID category.
        android_static_cat = (
            CATEGORIES[amo.ANDROID.id][amo.ADDON_EXTENSION]['sports-games'])
        and_category = Category.from_static_category(android_static_cat)
        and_category.save()
        AddonCategory.objects.create(addon=addon, category=and_category)

        # Reload the addon to get a fresh, uncached categories list.
        addon = get_addon()

        # Test that the ANDROID category was added correctly.
        assert sorted(addon.all_categories) == sorted(
            expected_firefox_cats + [android_static_cat])
        assert sorted(addon.app_categories.keys()) == ['android', 'firefox']
        assert addon.app_categories['firefox'] == expected_firefox_cats
        assert addon.app_categories['android'] == [android_static_cat]

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
        assert sorted(addon.all_categories) == sorted(expected_firefox_cats)
        assert addon.app_categories == {'firefox': expected_firefox_cats}

        # Associate this add-on with a couple more categories, including
        # one that does not exist in the constants.
        unknown_cat = Category.objects.create(
            application=amo.SUNBIRD.id, id=123456, type=amo.ADDON_EXTENSION)
        AddonCategory.objects.create(addon=addon, category=unknown_cat)
        android_static_cat = (
            CATEGORIES[amo.ANDROID.id][amo.ADDON_EXTENSION]['sports-games'])
        an_category = Category.from_static_category(android_static_cat)
        an_category.save()
        AddonCategory.objects.create(addon=addon, category=an_category)

        # Reload the addon to get a fresh, uncached categories list.
        addon = get_addon()

        # The sunbird category should not be present since it does not match
        # an existing static category, android one should have been added.
        assert sorted(addon.all_categories) == sorted(
            expected_firefox_cats + [android_static_cat])
        assert sorted(addon.app_categories.keys()) == ['android', 'firefox']
        assert addon.app_categories['firefox'] == expected_firefox_cats
        assert addon.app_categories['android'] == [android_static_cat]

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
        addon.update(status=amo.STATUS_APPROVED)
        addon.update(disabled_by_user=True)
        version.save()
        assert addon.status == amo.STATUS_APPROVED
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
        addon.update(status=amo.STATUS_APPROVED)
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
        self.check_can_request_review(amo.STATUS_APPROVED, False)

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
        assert mail.outbox[0].to == [settings.DELETION_EMAIL]

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
        a.status = amo.STATUS_APPROVED
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

        appname = getattr(amo.APP_IDS.get(amo.FIREFOX.id), 'short', '')
        assert addon.app_categories.get(appname)[0].name in names

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

    def test_listed_has_complete_metadata_no_name(self):
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Confirm complete already.

        delete_translation(addon, 'name')
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

    def test_auto_approval_delayed_until_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_delayed_until is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.auto_approval_delayed_until is None
        assert addon.auto_approval_delayed_until is None
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(auto_approval_delayed_until=in_the_past)
        assert addon.auto_approval_delayed_until == in_the_past

    def test_auto_approval_delayed_indefinitely_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_delayed_indefinitely is False
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert addon.auto_approval_delayed_indefinitely is False
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(auto_approval_delayed_until=in_the_past)
        assert addon.auto_approval_delayed_indefinitely is False
        # In the future, but not far enough.
        in_the_future = datetime.now() + timedelta(hours=24)
        flags.update(auto_approval_delayed_until=in_the_future)
        assert addon.auto_approval_delayed_indefinitely is False
        # This time it's truly delayed indefinitely.
        flags.update(auto_approval_delayed_until=datetime.max)
        assert addon.auto_approval_delayed_indefinitely is True

    def test_auto_approval_delayed_temporarily_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_delayed_temporarily is False
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert addon.auto_approval_delayed_temporarily is False
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(auto_approval_delayed_until=in_the_past)
        assert addon.auto_approval_delayed_temporarily is False
        # Flag present, now properly in the future.
        in_the_future = datetime.now() + timedelta(hours=24)
        flags.update(auto_approval_delayed_until=in_the_future)
        assert addon.auto_approval_delayed_temporarily is True
        # Not considered temporary any more if it's until the end of time!
        flags.update(auto_approval_delayed_until=datetime.max)
        assert addon.auto_approval_delayed_temporarily is False

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

    def test_attach_previews(self):
        addons = [addon_factory(), addon_factory(), addon_factory()]
        # Give some of the addons previews:
        # 2 for addons[0]
        pa = Preview.objects.create(addon=addons[0])
        pb = Preview.objects.create(addon=addons[0])
        # nothing for addons[1]; and 1 for addons[2]
        pc = Preview.objects.create(addon=addons[2])

        Addon.attach_previews(addons)

        # Create some more previews for [0] and [1].  As _all_previews and
        # _current_previews are cached_property-s then if attach_previews
        # worked then these new Previews won't be in the cached values.
        Preview.objects.create(addon=addons[0])
        Preview.objects.create(addon=addons[1])
        assert addons[0]._all_previews == [pa, pb]
        assert addons[1]._all_previews == []
        assert addons[2]._all_previews == [pc]
        assert addons[0].current_previews == [pa, pb]
        assert addons[1].current_previews == []
        assert addons[2].current_previews == [pc]

    def test_is_recommended(self):
        addon = addon_factory()
        # default case - no discovery item so not recommended
        assert not addon.is_recommended

        addon.current_version.update(recommendation_approved=True)
        disco = DiscoveryItem(addon=addon, recommendable=True)
        del addon.is_recommended
        # It's recommendable; and the latest version is approved too.
        assert addon.is_recommended

        disco.update(recommendable=False)
        del addon.is_recommended
        # we revoked the status, so now the addon shouldn't be recommended
        assert not addon.is_recommended

        addon.current_version.update(recommendation_approved=False)
        disco.update(recommendable=True)
        del addon.is_recommended
        # similarly if the current_version wasn't reviewed for recommended
        assert not addon.is_recommended

        addon.current_version.all_files[0].update(status=amo.STATUS_DISABLED)
        addon.update_version()
        assert not addon.current_version
        del addon.is_recommended
        # check it doesn't error if there's no current_version
        assert not addon.is_recommended

    def test_theme_is_recommended(self):
        # themes can be also recommended by being in featured themes collection
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        # check the default addon functionality first:
        # default case - no discovery item so not recommended
        assert not addon.is_recommended

        addon.current_version.update(recommendation_approved=True)
        disco = DiscoveryItem(addon=addon, recommendable=True)
        del addon.is_recommended
        # It's recommendable; and the latest version is approved too.
        assert addon.is_recommended

        disco.update(recommendable=False)
        del addon.is_recommended
        # we revoked the status, so now the addon shouldn't be recommended
        assert not addon.is_recommended

        featured_collection, _ = Collection.objects.get_or_create(
            id=settings.COLLECTION_FEATURED_THEMES_ID)
        featured_collection.add_addon(addon)
        del addon.is_recommended
        # it's in the collection, so is now recommended
        assert addon.is_recommended

        featured_collection.remove_addon(addon)
        del addon.is_recommended
        # but not when it's removed.
        assert not addon.is_recommended

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_field_changes_not_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        addon.update(
            average_rating=4.5, weekly_downloads=666, average_daily_users=999,
            last_updated=self.days_ago(1), public_stats=True,
            contributions='http://payme.example.com/',
            is_experimental=True)
        assert sync_object_to_basket_mock.delay.call_count == 0

        addon.homepage = 'http://home.example.com/'
        addon.description = 'Blâh Desc'
        addon.summary = 'Blâh Sum'
        addon.save()
        assert sync_object_to_basket_mock.delay.call_count == 0

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_field_changes_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        addon.update(default_locale='es')
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

        sync_object_to_basket_mock.reset_mock()
        addon.update(slug='some-fancy-slug')
        addon = Addon.objects.get(pk=3615)
        assert addon.slug == 'some-fancy-slug'
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

        sync_object_to_basket_mock.reset_mock()
        addon.update(disabled_by_user=True)
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_name_changes_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        addon.name = 'Blah'
        addon.save()

        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_deletion_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        addon.delete()
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_author_add_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=addon, user=user)
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_author_change_not_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        user = UserProfile.objects.get(pk=999)
        extra_author = AddonUser.objects.create(addon=addon, user=user)

        sync_object_to_basket_mock.reset_mock()
        extra_author.update(role=amo.AUTHOR_ROLE_DEV, listed=False)
        assert sync_object_to_basket_mock.delay.call_count == 0

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_author_delete_synced_to_basket(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        user = UserProfile.objects.get(pk=999)
        extra_author = AddonUser.objects.create(addon=addon, user=user)

        sync_object_to_basket_mock.reset_mock()
        extra_author.delete()
        assert sync_object_to_basket_mock.delay.call_count == 1
        assert sync_object_to_basket_mock.delay.called_with(
            'addon', 3615)

    @patch('olympia.amo.tasks.sync_object_to_basket')
    def test_addon_author_delete_not_synced_to_basket_if_addon_is_deleted(
            self, sync_object_to_basket_mock):
        addon = Addon.objects.get(id=3615)
        user = UserProfile.objects.get(pk=999)
        extra_author = AddonUser.objects.create(addon=addon, user=user)
        addon.delete()

        sync_object_to_basket_mock.reset_mock()
        extra_author.delete()
        assert sync_object_to_basket_mock.delay.call_count == 0

    def test_block_property(self):
        addon = Addon.objects.get(id=3615)
        assert addon.block is None

        del addon.block
        block = Block.objects.create(
            guid=addon.guid, updated_by=user_factory())
        assert addon.block == block

        del addon.block
        block.update(guid='not-a-guid')
        assert addon.block is None

    def test_blocklistsubmission_property(self):
        addon = Addon.objects.get(id=3615)
        assert addon.blocklistsubmission is None

        del addon.blocklistsubmission
        submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, updated_by=user_factory())
        assert addon.blocklistsubmission == submission

        del addon.blocklistsubmission
        submission.update(input_guids='not-a-guid')
        submission.update(to_block=None)
        assert addon.blocklistsubmission is None


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

    def test_has_listed_versions_current_version_shortcut(self):
        # We shouldn't even do a exists() query if the add-on has a
        # current_version.
        self.addon._current_version_id = 123
        assert self.addon.has_listed_versions()

    def test_has_listed_versions_soft_delete(self):
        version_factory(
            channel=amo.RELEASE_CHANNEL_LISTED, addon=self.addon, deleted=True)
        version_factory(
            channel=amo.RELEASE_CHANNEL_UNLISTED, addon=self.addon)
        assert not self.addon.has_listed_versions()
        assert self.addon.has_listed_versions(include_deleted=True)

    def test_has_unlisted_versions_soft_delete(self):
        version_factory(
            channel=amo.RELEASE_CHANNEL_UNLISTED, addon=self.addon,
            deleted=True)
        version_factory(
            channel=amo.RELEASE_CHANNEL_LISTED, addon=self.addon)
        assert not self.addon.has_unlisted_versions()
        assert self.addon.has_unlisted_versions(include_deleted=True)


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
        for st in (amo.STATUS_APPROVED, amo.STATUS_NULL):
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
        File.objects.create(status=amo.STATUS_APPROVED, version=version)
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
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED)
        # Now create a new version with an attached file, and update status.
        self.check_nomination_reset_with_new_version(addon, nomination)


class TestAddonDelete(TestCase):

    def test_cascades(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

        AddonCategory.objects.create(
            addon=addon,
            category=Category.objects.create(type=amo.ADDON_EXTENSION))
        AddonUser.objects.create(
            addon=addon, user=UserProfile.objects.create())
        AppSupport.objects.create(addon=addon, app=1)
        FrozenAddon.objects.create(addon=addon)

        AddonLog.objects.create(
            addon=addon, activity_log=ActivityLog.objects.create(action=0))
        RssKey.objects.create(addon=addon)

        # This should not throw any FK errors if all the cascades work.
        addon.delete()
        # Make sure it was actually a hard delete.
        assert not Addon.unfiltered.filter(pk=addon.pk).exists()

    def test_review_delete(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     status=amo.STATUS_APPROVED)

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
        file_ = File.objects.create(
            status=amo.STATUS_AWAITING_REVIEW, version=version)
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NOMINATED)
        file_.status = amo.STATUS_DISABLED
        file_.save()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NULL)

    def test_unlisted_versions_ignored(self):
        addon = addon_factory(status=amo.STATUS_APPROVED)
        addon.update_status()
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_APPROVED)

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
            addon=self.addon, file_kw={'status': amo.STATUS_APPROVED})
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
            file_kw={'status': amo.STATUS_APPROVED})
        assert new_version != self.version
        # Since the new version is unlisted, find_latest_public_listed_version
        # should still find the current one.
        assert self.addon.find_latest_public_listed_version() == self.version


class TestAddonGetURLPath(TestCase):

    def test_get_url_path(self):
        addon = addon_factory(slug='woo')
        assert addon.get_url_path() == '/en-US/firefox/addon/woo/'

    def test_unlisted_addon_get_url_path(self):
        addon = addon_factory(
            slug='woo', version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        assert addon.get_url_path() == ''


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

    def test_name_fallback_to_empty(self):
        category = Category.objects.create(
            type=amo.ADDON_EXTENSION, application=amo.FIREFOX.id,
            slug='this-cat-does-not-exist')

        assert category.name == u''
        with translation.override('fr'):
            assert category.name == u''


class TestPreviewModel(BasePreviewMixin, TestCase):
    fixtures = ['base/previews']

    def get_object(self):
        return Preview.objects.get(pk=24)


class TestListedAddonTwoVersions(TestCase):
    fixtures = ['addons/listed-two-versions']

    def test_listed_two_versions(self):
        Addon.objects.get(id=2795)  # bug 563967


class TestAddonFromUpload(UploadTest):
    fixtures = ['base/users']

    @classmethod
    def setUpTestData(self):
        versions = {
            '3.0',
            '3.6.*',
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MIN_VERSION_NO_ID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.create(
                application=amo.FIREFOX.id, version=version)
            AppVersion.objects.create(
                application=amo.ANDROID.id, version=version)

    def setUp(self):
        super(TestAddonFromUpload, self).setUp()
        self.selected_app = amo.FIREFOX.id
        self.user = UserProfile.objects.get(pk=999)
        self.addCleanup(translation.deactivate)

        def _app(application):
            return Extractor.App(
                appdata=application, id=application.id,
                min=AppVersion.objects.get(
                    application=application.id, version='3.0'),
                max=AppVersion.objects.get(
                    application=application.id, version='3.6.*'))

        self.dummy_parsed_data = {
            'guid': 'guid@xpi',
            'version': '0.1',
            'apps': [_app(amo.FIREFOX)]
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
            parse_addon(self.get_upload('extension.xpi'), user=self.user)
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid(self):
        # Upload addon so we can delete it.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        deleted = Addon.from_upload(self.upload, [self.selected_app],
                                    parsed_data=parsed_data)
        deleted.update(status=amo.STATUS_APPROVED)
        deleted.delete()
        assert deleted.guid == 'guid@xpi'

        # Now upload the same add-on again (so same guid).
        with self.assertRaises(forms.ValidationError) as e:
            self.upload = self.get_upload('extension.xpi')
            parse_addon(self.upload, user=self.user)
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid_same_author(self):
        # Upload addon so we can delete it.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        deleted = Addon.from_upload(self.upload, [self.selected_app],
                                    parsed_data=parsed_data)
        # Claim the add-on.
        AddonUser(addon=deleted, user=self.user).save()
        deleted.update(status=amo.STATUS_APPROVED)
        deleted.delete()
        assert deleted.guid == 'guid@xpi'

        # Now upload the same add-on again (so same guid), checking no
        # validationError is raised this time.
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(self.upload, [self.selected_app],
                                  parsed_data=parsed_data)
        deleted.reload()
        assert addon.guid == 'guid@xpi'
        assert deleted.guid == 'guid-reused-by-pk-%s' % addon.pk
        assert ReusedGUID.objects.filter(guid='guid@xpi').count() == 1
        assert ReusedGUID.objects.filter(guid='guid@xpi').last().addon == (
            deleted)

    def test_old_soft_deleted_addons_and_upload_non_extension(self):
        """We used to just null out GUIDs on soft deleted addons. This test
        makes sure we don't fail badly when uploading an add-on which isn't an
        extension (has no GUID).
        See https://github.com/mozilla/addons-server/issues/1659."""
        # Upload a couple of addons so we can pretend they were soft deleted.
        deleted1 = Addon.from_upload(
            self.get_upload('extension.xpi'), [self.selected_app],
            parsed_data=self.dummy_parsed_data)
        deleted2 = Addon.from_upload(
            self.get_upload('alt-rdf.xpi'), [self.selected_app],
            parsed_data=self.dummy_parsed_data)
        AddonUser(addon=deleted1, user=self.user).save()
        AddonUser(addon=deleted2, user=self.user).save()

        # Soft delete them like they were before, by nullifying their GUIDs.
        deleted1.update(status=amo.STATUS_APPROVED, guid=None)
        deleted2.update(status=amo.STATUS_APPROVED, guid=None)

        # Now upload a new add-on which isn't an extension, and has no GUID.
        # This fails if we try to reclaim the GUID from deleted add-ons: the
        # GUID is None, so it'll try to get the add-on that has a GUID which is
        # None, but many are returned. So make sure we're not trying to reclaim
        # the GUID.
        self.upload = self.get_upload('search.xml')
        parsed_data = parse_addon(self.upload, user=self.user)
        Addon.from_upload(
            self.upload, [self.selected_app], parsed_data=parsed_data)

    def test_xpi_attributes(self):
        self.upload = self.get_upload('extension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(self.upload, [self.selected_app],
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
                                  [self.selected_app],
                                  parsed_data=self.dummy_parsed_data)
        version = addon.versions.get()
        assert version.version == '0.1'
        assert len(version.compatible_apps.keys()) == 1
        assert list(version.compatible_apps.keys())[0].id == self.selected_app
        assert version.files.get().platform == amo.PLATFORM_ALL.id
        assert version.files.get().status == amo.STATUS_AWAITING_REVIEW

    def test_platforms(self):
        # We are defaulting to PLATFORM_ALL for all uploads as part of
        # removing platforms in favour of ApplicationsVersions
        # See #8572 for more details.
        addon = Addon.from_upload(
            self.get_upload('extension.xpi'),
            [amo.FIREFOX.id, amo.ANDROID.id],
            parsed_data=self.dummy_parsed_data)
        version = addon.versions.get()
        assert sorted([file_.platform for file_ in version.all_files]) == (
            [amo.PLATFORM_ALL.id])

    def test_search_attributes(self):
        self.upload = self.get_upload('search.xml')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(self.upload, [self.selected_app],
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
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, [self.selected_app], parsed_data=parsed_data)
        version = addon.versions.get()
        assert version.version == datetime.now().strftime('%Y%m%d')
        assert version.files.get().platform == amo.PLATFORM_ALL.id
        assert version.files.get().status == amo.STATUS_AWAITING_REVIEW

    def test_no_homepage(self):
        addon = Addon.from_upload(
            self.get_upload('extension-no-homepage.xpi'),
            [self.selected_app],
            parsed_data=self.dummy_parsed_data)
        assert addon.homepage is None

    def test_default_locale(self):
        # Make sure default_locale follows the active translation.
        addon = Addon.from_upload(
            self.get_upload('search.xml'),
            [self.selected_app], parsed_data=self.dummy_parsed_data)
        assert addon.default_locale == 'en-US'

        translation.activate('es')
        addon = Addon.from_upload(
            self.get_upload('search.xml'),
            [self.selected_app], parsed_data=self.dummy_parsed_data)
        assert addon.default_locale == 'es'

    def test_validation_completes(self):
        upload = self.get_upload('extension.xpi')
        assert not upload.validation_timeout
        addon = Addon.from_upload(
            upload, [self.selected_app], parsed_data=self.dummy_parsed_data)
        assert not addon.needs_admin_code_review
        assert not addon.auto_approval_disabled

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
            upload, [self.selected_app], parsed_data=self.dummy_parsed_data)
        assert addon.needs_admin_code_review
        assert not addon.auto_approval_disabled

    def test_mozilla_signed(self):
        upload = self.get_upload('extension.xpi')
        assert not upload.validation_timeout
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        addon = Addon.from_upload(
            upload, [self.selected_app], parsed_data=self.dummy_parsed_data)
        assert addon.needs_admin_code_review
        assert addon.auto_approval_disabled

    def test_mozilla_signed_langpack(self):
        upload = self.get_upload('extension.xpi')
        assert not upload.validation_timeout
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        self.dummy_parsed_data['type'] = amo.ADDON_LPAPP
        addon = Addon.from_upload(
            upload, [self.selected_app], parsed_data=self.dummy_parsed_data)
        assert not addon.needs_admin_code_review
        assert not addon.auto_approval_disabled

    def test_webextension_generate_guid(self):
        self.upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, [self.selected_app], parsed_data=parsed_data)

        assert addon.guid is not None
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

        # Uploading the same addon without a id works.
        self.upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        new_addon = Addon.from_upload(
            self.upload, [self.selected_app], parsed_data=parsed_data)
        assert new_addon.guid is not None
        assert new_addon.guid != addon.guid
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

    def test_webextension_reuse_guid(self):
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, [self.selected_app], parsed_data=parsed_data)

        assert addon.guid == '@webextension-guid'

        # Uploading the same addon with pre-existing id fails
        with self.assertRaises(forms.ValidationError) as e:
            self.upload = self.get_upload('webextension.xpi')
            parsed_data = parse_addon(self.upload, user=self.user)
            Addon.from_upload(self.upload, [self.selected_app],
                              parsed_data=parsed_data)
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_webextension_resolve_translations(self):
        self.upload = self.get_upload('notify-link-clicks-i18n.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, [self.selected_app], parsed_data=parsed_data)

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
            [self.selected_app], parsed_data=parsed_data)

        # Normalized from `sv` to `sv-SE`
        assert addon.default_locale == 'sv-SE'

    def test_webext_resolve_translations_unknown_locale(self):
        """Make sure we use our default language as default
        for invalid locales
        """
        parsed_data = {
            'default_locale': u'xxx',
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
            [self.selected_app], parsed_data=parsed_data)

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
        addon = Addon.objects.create(type=amo.ADDON_DICT)
        version = Version.objects.create(addon=addon)
        version.release_notes = {'fr': 'oui'}
        version.save()
        addon.remove_locale('fr')
        assert not (Translation.objects.filter(localized_string__isnull=False)
                               .values_list('locale', flat=True))


class TestAddonWatchDisabled(TestCase):

    def setUp(self):
        super(TestAddonWatchDisabled, self).setUp()
        self.addon = Addon(type=amo.ADDON_DICT, disabled_by_user=False,
                           status=amo.STATUS_APPROVED)
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
        self.addon.update(status=amo.STATUS_APPROVED)
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
            addon.update(status=amo.STATUS_APPROVED)

        addon.reload()
        mock_.call_args[0][0].status == addon.status

    def test_ignore_non_status_changes(self):
        addon = self.create_addon()
        with patch('olympia.addons.models.track_addon_status_change') as mock_:
            addon.update(type=amo.ADDON_DICT)
        assert not mock_.called, (
            'Unexpected call: {}'.format(self.mock_incr.call_args)
        )

    def test_increment_all_addon_statuses(self):
        addon = self.create_addon(status=amo.STATUS_APPROVED)
        with patch('olympia.addons.models.statsd.incr') as mock_incr:
            track_addon_status_change(addon)
        mock_incr.assert_any_call(
            'addon_status_change.all.status_{}'.format(amo.STATUS_APPROVED)
        )


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
        self.static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        MigratedLWT.objects.create(
            lightweight_theme_id=666,
            getpersonas_id=999,
            static_theme=self.static_theme)

    def test_addon_id_lookup(self):
        match = MigratedLWT.objects.get(lightweight_theme_id=666)
        assert match.static_theme == self.static_theme

    def test_getpersonas_id_lookup(self):
        match = MigratedLWT.objects.get(getpersonas_id=999)
        assert match.static_theme == self.static_theme


class TestAddonAndDeniedGuid(TestCase):
    def setUp(self):
        # This is needed for the `ActivityLog`.
        core.set_user(UserProfile.objects.create(pk=999))

    def get_last_activity_log(self):
        return ActivityLog.objects.order_by('id').last()

    def test_is_guid_denied(self):
        addon = addon_factory()
        assert not addon.is_guid_denied
        DeniedGuid.objects.create(guid=addon.guid)
        assert addon.is_guid_denied

    def test_deny_resubmission(self):
        addon = addon_factory()
        assert not DeniedGuid.objects.filter(guid=addon.guid).exists()
        addon.deny_resubmission()
        assert DeniedGuid.objects.filter(guid=addon.guid).exists()
        last_activity = self.get_last_activity_log()
        assert last_activity.action == amo.LOG.DENIED_GUID_ADDED.id

    def test_deny_already_denied_guid(self):
        addon = addon_factory()
        addon.deny_resubmission()
        with pytest.raises(RuntimeError):
            addon.deny_resubmission()

    def test_allow_resubmission(self):
        addon = addon_factory()
        addon.deny_resubmission()
        assert DeniedGuid.objects.filter(guid=addon.guid).exists()
        addon.allow_resubmission()
        assert not DeniedGuid.objects.filter(guid=addon.guid).exists()
        last_activity = self.get_last_activity_log()
        assert last_activity.action == amo.LOG.DENIED_GUID_DELETED.id

    def test_allow_resubmission_with_non_denied_guid(self):
        addon = addon_factory()
        with pytest.raises(RuntimeError):
            addon.allow_resubmission()


class TestAddonGitExtraction(TestCase):
    def test_git_extraction_is_in_progress_returns_false_when_no_attr(self):
        addon = addon_factory()
        assert not addon.git_extraction_is_in_progress

    def test_git_extraction_is_in_progress(self):
        addon = addon_factory()
        AddonGitExtraction.objects.create(addon=addon, in_progress=True)
        assert addon.git_extraction_is_in_progress

    def test_git_extraction_is_not_in_progress(self):
        addon = addon_factory()
        AddonGitExtraction.objects.create(addon=addon, in_progress=False)
        assert not addon.git_extraction_is_in_progress
