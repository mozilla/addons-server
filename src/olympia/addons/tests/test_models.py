import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from django import forms
from django.conf import settings
from django.core import mail
from django.db import IntegrityError
from django.utils import translation

import pytest
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.activity.models import ActivityLog, AddonLog
from olympia.addons import models as addons_models
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonCategory,
    AddonGUID,
    AddonListingInfo,
    AddonRegionalRestrictions,
    AddonReviewerFlags,
    AddonUser,
    DeniedGuid,
    DeniedSlug,
    FrozenAddon,
    GuidAlreadyDeniedError,
    MigratedLWT,
    Preview,
    track_addon_status_change,
)
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.amo.tests.test_models import BasePreviewMixin
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.blocklist.models import Block, BlocklistSubmission, BlockType, BlockVersion
from olympia.constants.categories import CATEGORIES
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.devhub.models import RssKey
from olympia.files.models import File
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
    PromotedGroup,
)
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.translations.models import (
    Translation,
    TranslationSequence,
    delete_translation,
)
from olympia.users.models import UserProfile
from olympia.versions.models import (
    ApplicationsVersions,
    Version,
    VersionPreview,
    VersionProvenance,
    VersionReviewerFlags,
)
from olympia.zadmin.models import set_config


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
    @patch.object(addons_models, 'SLUG_INCREMENT_SUFFIXES', set(range(1, 99 + 1)))
    def test_clean_slug_worst_case_scenario(self):
        long_slug = 'this_is_a_very_long_slug_that_is_longer_than_thirty_chars'

        # Generate 100 addons with this very long slug. We should encounter the
        # worst case scenario where all the available clashes have been
        # avoided. Check the comment in addons.models.clean_slug, in the 'else'
        # part of the 'for" loop checking for available slugs not yet assigned.
        for _i in range(100):
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
        addon = Addon.objects.create(name='Addön 1')
        assert addon.slug == 'addön-1'

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
    fixtures = [
        'base/appversion',
        'base/users',
        'base/addon_3615',
        'addons/test_manager',
        'base/collections',
        'base/featured',
        'base/addon_5299_gcal',
    ]

    def setUp(self):
        super().setUp()
        core.set_user(None)
        self.addon = Addon.objects.get(pk=3615)

    def test_managers_public(self):
        assert self.addon in Addon.objects.all()
        assert self.addon in Addon.unfiltered.all()

    def test_managers_not_disabled_by_mozilla(self):
        assert self.addon in Addon.objects.not_disabled_by_mozilla()
        assert self.addon in Addon.unfiltered.not_disabled_by_mozilla()

        self.addon.update(status=amo.STATUS_DISABLED)

        assert self.addon not in Addon.objects.not_disabled_by_mozilla()
        assert self.addon not in Addon.unfiltered.not_disabled_by_mozilla()

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
    fixtures = [
        'base/appversion',
        'base/collections',
        'base/users',
        'base/addon_5299_gcal',
        'base/addon_3615',
        'base/addon_3723_listed',
        'base/addon_4664_twitterbar',
        'addons/denied',
    ]

    def setUp(self):
        super().setUp()
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
            addon=addon, version='3.0', channel=amo.CHANNEL_UNLISTED
        )
        an_unlisted_version.update(created=self.days_ago(2))
        a_newer_unlisted_version = version_factory(
            addon=addon, version='4.0', channel=amo.CHANNEL_UNLISTED
        )
        a_newer_unlisted_version.update(created=self.days_ago(1))
        version_factory(
            addon=addon,
            version='5.0',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        assert addon.latest_unlisted_version == a_newer_unlisted_version

        # Make sure the property is cached.
        an_even_newer_unlisted_version = version_factory(
            addon=addon, version='6.0', channel=amo.CHANNEL_UNLISTED
        )
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
            addon=addon, version='3.0', channel=amo.CHANNEL_UNLISTED
        )
        assert addon.find_latest_version(None) == another_new_version

    def test_find_latest_version_different_channel(self):
        addon = Addon.objects.get(pk=3615)
        addon.current_version.update(created=self.days_ago(2))
        new_version = version_factory(addon=addon, version='2.0')
        new_version.update(created=self.days_ago(1))
        unlisted_version = version_factory(
            addon=addon, version='3.0', channel=amo.CHANNEL_UNLISTED
        )

        assert addon.find_latest_version(channel=amo.CHANNEL_LISTED) == new_version
        assert (
            addon.find_latest_version(channel=amo.CHANNEL_UNLISTED) == unlisted_version
        )

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

        version_factory(
            addon=addon, version='2.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        # Still should be v1
        assert addon.find_latest_version(None).id == v1.id

    def test_find_latest_version_dont_exclude_anything(self):
        addon = Addon.objects.get(pk=3615)

        v1 = version_factory(addon=addon, version='1.0')
        v1.update(created=self.days_ago(2))

        assert addon.find_latest_version(None, exclude=()).id == v1.id

        v2 = version_factory(
            addon=addon, version='2.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        v2.update(created=self.days_ago(1))

        # Should be v2 since we don't exclude anything.
        assert addon.find_latest_version(None, exclude=()).id == v2.id

    def test_find_latest_version_dont_exclude_anything_with_channel(self):
        addon = Addon.objects.get(pk=3615)

        v1 = version_factory(addon=addon, version='1.0')
        v1.update(created=self.days_ago(3))

        assert addon.find_latest_version(amo.CHANNEL_LISTED, exclude=()).id == v1.id

        v2 = version_factory(
            addon=addon, version='2.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        v2.update(created=self.days_ago(1))

        version_factory(addon=addon, version='4.0', channel=amo.CHANNEL_UNLISTED)

        # Should be v2 since we don't exclude anything, but do have a channel
        # set to listed, and version 4.0 is unlisted.
        assert addon.find_latest_version(amo.CHANNEL_LISTED, exclude=()).id == v2.id

    def test_find_latest_version_include_deleted(self):
        addon = Addon.objects.get(pk=3615)
        v0 = addon.current_version

        v1 = version_factory(addon=addon, version='1.0')
        v1.update(created=self.days_ago(1))
        v1.delete()
        assert addon.find_latest_version(None, exclude=()).id == v0.id
        assert addon.find_latest_version(None, exclude=(), deleted=True).id == v1.id

        addon.delete()
        assert addon.find_latest_version(None, exclude=()) is None
        assert addon.find_latest_version(None, exclude=(), deleted=True).id == v1.id

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
            addon_id=3615, user=user_factory(username='new_author'), listed=True
        ).user
        # make the new_author a deleted author of another addon
        AddonUser.objects.create(
            addon=addon_factory(), user=new_author, role=amo.AUTHOR_ROLE_DELETED
        )
        # Deleted, so shouldn't show up below.
        AddonUser.objects.create(
            addon_id=3615,
            user=user_factory(username='deleted_author'),
            listed=True,
            role=amo.AUTHOR_ROLE_DELETED,
        )
        # Not listed, should not show up.
        AddonUser.objects.create(
            addon_id=3615,
            user=user_factory(username='not_listed_author'),
            listed=False,
            role=amo.AUTHOR_ROLE_OWNER,
        )
        # Different author on another add-on - should not show up
        AddonUser.objects.create(addon=addon_factory(), user=user_factory())
        # First author, but on another add-on, not deleted - should not show up
        AddonUser.objects.create(addon=addon_factory(), user=author)

        # Force evaluation of the queryset and test a single add-on
        addon = list(Addon.objects.all().order_by('pk'))[0]

        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            assert addon.current_version
            # Use list() so that we evaluate a queryset in case the
            # transformer didn't attach the list directly
            assert [u.pk for u in addon.listed_authors] == [author.pk, new_author.pk]

        # repeat to check the position ordering works
        author.addonuser_set.filter(addon=addon).update(position=1)
        addon = Addon.objects.get(pk=3615)
        with self.assertNumQueries(0):
            assert [u.pk for u in addon.listed_authors] == [new_author.pk, author.pk]

    def test_transformer_all_authors(self):
        author = UserProfile.objects.get(pk=55021)
        new_author = AddonUser.objects.create(
            addon_id=3615, user=user_factory(username='new_author'), listed=True
        ).user
        # make the new_author a deleted author of another addon
        AddonUser.objects.create(
            addon=addon_factory(), user=new_author, role=amo.AUTHOR_ROLE_DELETED
        )
        # Deleted, so it should show up cause we're looking at *all* authors
        # explicitly.
        deleted_author = AddonUser.objects.create(
            addon_id=3615,
            user=user_factory(username='deleted_author'),
            listed=True,
            role=amo.AUTHOR_ROLE_DELETED,
        ).user
        # Not listed, should also show up.
        not_listed_author = AddonUser.objects.create(
            addon_id=3615,
            user=user_factory(username='not_listed_author'),
            listed=False,
            role=amo.AUTHOR_ROLE_OWNER,
        ).user
        # Different author on another add-on - should not show up
        AddonUser.objects.create(addon=addon_factory(), user=user_factory())
        # First author, but on another add-on, not deleted - should not show up
        AddonUser.objects.create(addon=addon_factory(), user=author)

        # Force evaluation of the queryset and test a single add-on
        addon = list(Addon.objects.transform(Addon.attach_all_authors).order_by('pk'))[
            0
        ]

        # If the transformer works then we won't have any more queries.
        with self.assertNumQueries(0):
            assert [u.pk for u in addon.all_authors] == [
                author.pk,
                new_author.pk,
                deleted_author.pk,
                not_listed_author.pk,
            ]
        for user in addon.all_authors:
            addonuser = AddonUser.unfiltered.filter(user=user, addon=addon).get()
            assert user.role == addonuser.role
            assert user.listed == addonuser.listed

    def _delete(self, addon_id):
        """Test deleting add-ons."""
        core.set_user(UserProfile.objects.last())
        addon_count = Addon.unfiltered.count()
        addon = Addon.objects.get(pk=addon_id)
        guid = addon.guid
        addon.delete(msg='bye')
        assert addon_count == Addon.unfiltered.count()  # Soft deletion.
        assert addon.status == amo.STATUS_DELETED
        assert addon.slug is None
        assert addon.current_version is None
        assert addon.guid == guid  # We don't clear it anymore.
        deleted_count = Addon.unfiltered.filter(status=amo.STATUS_DELETED).count()
        assert len(mail.outbox) == deleted_count
        log = AddonLog.objects.order_by('-id').first().activity_log
        assert log.action == amo.LOG.DELETE_ADDON.id
        assert log.to_string() == (
            f'Add-on id {addon_id} with GUID {guid} has been deleted'
        )

    def test_delete(self):
        addon = Addon.unfiltered.get(pk=3615)
        addon.name = 'é'  # Make sure we don't have encoding issues.
        addon.save()
        self._delete(3615)

        # Delete another add-on, and make sure we don't have integrity errors
        # with unique constraints on fields that got nullified.
        self._delete(5299)

    @patch('olympia.addons.tasks.Preview.delete_preview_files')
    @patch('olympia.versions.tasks.VersionPreview.delete_preview_files')
    def test_delete_deletes_preview_files(self, dpf_vesions_mock, dpf_addons_mock):
        addon = addon_factory()
        addon_preview = Preview.objects.create(addon=addon)
        version_preview = VersionPreview.objects.create(version=addon.current_version)
        addon.delete()
        dpf_addons_mock.assert_called_with(sender=None, instance=addon_preview)
        dpf_vesions_mock.assert_called_with(sender=None, instance=version_preview)

    def test_delete_clear_pending_rejection(self):
        addon = addon_factory()
        user = user_factory()
        version_factory(addon=addon)
        other_addon = addon_factory()
        for version in Version.objects.all():
            version_review_flags_factory(
                version=version,
                pending_rejection=datetime.now() + timedelta(days=1),
                pending_rejection_by=user,
            )
        assert VersionReviewerFlags.objects.filter(version__addon=addon).exists()
        addon.delete()
        assert addon.versions(manager='unfiltered_for_relations').exists()
        # There shouldn't be any version reviewer flags for versions of that
        # add-on with a non-null pending rejection anymore.
        assert not VersionReviewerFlags.objects.filter(
            version__addon=addon,
            pending_rejection__isnull=False,
        ).exists()
        # There should still be one for the version of the other add-on though.
        assert VersionReviewerFlags.objects.filter(
            version__addon=other_addon,
            pending_rejection__isnull=False,
            pending_rejection_by=user,
        ).exists()
        # pending_rejection_by should have been cleared for those not pending
        # rejection.
        assert (
            VersionReviewerFlags.objects.filter(
                version__addon=other_addon,
                pending_rejection_by=user,
            ).count()
            == 1
        )

    def test_delete_reason(self):
        """Test deleting with a reason gives the reason in the mail."""
        reason = 'trêason'
        a = Addon.objects.get(pk=3615)
        a.name = 'é'
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
        addon.delete(msg=None)
        assert len(mail.outbox) == 0
        assert Addon.unfiltered.count() == (count - 1)

    def test_delete_incomplete_with_versions(self):
        """Test deleting incomplete add-ons."""
        count = Addon.unfiltered.count()
        a = Addon.objects.get(pk=3615)
        a.status = 0
        a.save()
        a.delete(msg='oh looky here')
        assert len(mail.outbox) == 1
        assert count == Addon.unfiltered.count()

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

    def test_delete_disabled_addon_no_guid(self):
        addon = Addon.unfiltered.get(pk=3615)
        addon.update(status=amo.STATUS_DISABLED, guid=None)
        self._delete(3615)
        # Adding it to the DeniedGuid would be pointless since it's empty. The
        # important thing is that the delete() calls succeeds.
        assert not DeniedGuid.objects.filter(guid=addon.guid).exists()

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
            assert (
                file_.status_disabled_reason
                == File.STATUS_DISABLED_REASONS.ADDON_DELETE
            )
        for version in versions:
            assert version.deleted

    @patch('olympia.addons.tasks.delete_all_addon_media_with_backup')
    def test_force_disable(self, delete_all_addon_media_with_backup_mock):
        core.set_user(UserProfile.objects.get(email='admin@mozilla.com'))
        addon = Addon.unfiltered.get(pk=3615)
        version1 = version_factory(addon=addon)
        NeedsHumanReview.objects.create(version=version1, is_active=True)
        version2 = version_factory(
            addon=addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        NeedsHumanReview.objects.create(version=version2, is_active=True)
        assert addon.status != amo.STATUS_DISABLED
        files = File.objects.filter(version__addon=addon)
        assert files
        for file_ in files:
            assert file_.status != amo.STATUS_DISABLED
        already_disabled_version = version_factory(
            addon=addon,
            file_kw={
                'status': amo.STATUS_DISABLED,
                'status_disabled_reason': File.STATUS_DISABLED_REASONS.DEVELOPER,
            },
        )
        assert version1.due_date
        assert version2.due_date

        addon.force_disable()

        log = ActivityLog.objects.latest('pk')
        assert log.action == amo.LOG.FORCE_DISABLE.id

        assert addon.status == amo.STATUS_DISABLED
        files = File.objects.filter(version__addon=addon)
        assert files
        for file_ in files:
            assert file_.status == amo.STATUS_DISABLED
            if file_.version == already_disabled_version:
                assert (
                    file_.status_disabled_reason
                    == File.STATUS_DISABLED_REASONS.DEVELOPER
                )
            else:
                assert (
                    file_.status_disabled_reason
                    == File.STATUS_DISABLED_REASONS.ADDON_DISABLE
                )
                assert file_.original_status in (
                    amo.STATUS_APPROVED,
                    amo.STATUS_AWAITING_REVIEW,
                )
            assert not file_.version.due_date
            assert not file_.version.needshumanreview_set.filter(
                is_active=True
            ).exists()

        assert delete_all_addon_media_with_backup_mock.delay.call_count == 1
        assert delete_all_addon_media_with_backup_mock.delay.call_args[0] == (addon.pk,)

    def test_force_disable_works_if_status_is_listing_rejected(self):
        addon = Addon.unfiltered.get(pk=3615)
        addon.update(status=amo.STATUS_REJECTED)
        self.test_force_disable()

    def test_force_disable_clear_due_date_unlisted_auto_approval_indefinite_delay(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        version = version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        AddonReviewerFlags.objects.create(
            addon=addon, auto_approval_delayed_until_unlisted=datetime.max
        )
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        version.reset_due_date()
        assert version.due_date is not None
        addon.force_disable()
        version.reload()
        assert version.due_date is None

    def test_force_disable_skip_activity_log(self):
        core.set_user(UserProfile.objects.get(email='admin@mozilla.com'))
        addon = Addon.unfiltered.get(pk=3615)
        assert addon.status != amo.STATUS_DISABLED
        ActivityLog.objects.all().delete()
        addon.force_disable(skip_activity_log=True)
        assert addon.status == amo.STATUS_DISABLED
        assert not ActivityLog.objects.exists()

    @patch('olympia.addons.tasks.restore_all_addon_media_from_backup')
    def test_force_enable(self, restore_all_addon_media_from_backup_mock):
        core.set_user(UserProfile.objects.get(email='admin@mozilla.com'))
        addon = Addon.unfiltered.get(pk=3615)
        v1 = addon.current_version
        v2 = version_factory(addon=addon)
        v3 = version_factory(addon=addon)
        addon.update(status=amo.STATUS_DISABLED)
        v1.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # We don't want to re-enable a version the developer disabled
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
        )
        v2.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # we also don't want to re-enable a version we rejected
            status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
        )
        v3.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # but we do want to re-enable a version we only disabled with the addon
            status_disabled_reason=File.STATUS_DISABLED_REASONS.ADDON_DISABLE,
        )

        addon.force_enable()
        assert addon.reload().status == amo.STATUS_APPROVED
        assert v1.file.reload().status == amo.STATUS_DISABLED
        assert v2.file.reload().status == amo.STATUS_DISABLED
        assert v3.file.reload().status == amo.STATUS_APPROVED
        log = ActivityLog.objects.latest('pk')
        assert log.action == amo.LOG.FORCE_ENABLE.id

        assert restore_all_addon_media_from_backup_mock.delay.call_count == 1
        assert restore_all_addon_media_from_backup_mock.delay.call_args[0] == (
            addon.pk,
        )

    @patch('olympia.addons.tasks.restore_all_addon_media_from_backup')
    def test_force_enable_back_to_rejected(
        self, restore_all_addon_media_from_backup_mock
    ):
        core.set_user(UserProfile.objects.get(email='admin@mozilla.com'))
        addon = Addon.unfiltered.get(pk=3615)
        v1 = addon.current_version
        v2 = version_factory(addon=addon)
        v3 = version_factory(addon=addon)
        AddonApprovalsCounter.objects.create(
            addon=addon, last_content_review_pass=False
        )
        addon.update(status=amo.STATUS_DISABLED)
        v1.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # We don't want to re-enable a version the developer disabled
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
        )
        v2.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # we also don't want to re-enable a version we rejected
            status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
        )
        v3.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # but we do want to re-enable a version we only disabled with the addon
            status_disabled_reason=File.STATUS_DISABLED_REASONS.ADDON_DISABLE,
        )

        addon.force_enable()
        assert addon.reload().status == amo.STATUS_REJECTED
        assert v1.file.reload().status == amo.STATUS_DISABLED
        assert v2.file.reload().status == amo.STATUS_DISABLED
        assert v3.file.reload().status == amo.STATUS_APPROVED
        assert ActivityLog.objects.latest('pk').action == amo.LOG.CHANGE_STATUS.id
        assert (
            ActivityLog.objects.exclude(action=amo.LOG.CHANGE_STATUS.id)
            .latest('pk')
            .action
            == amo.LOG.FORCE_ENABLE.id
        )

        assert restore_all_addon_media_from_backup_mock.delay.call_count == 1
        assert restore_all_addon_media_from_backup_mock.delay.call_args[0] == (
            addon.pk,
        )

    def test_force_enable_skip_activity_log(self):
        core.set_user(UserProfile.objects.get(email='admin@mozilla.com'))
        addon = Addon.unfiltered.get(pk=3615)
        addon.update(status=amo.STATUS_DISABLED)
        ActivityLog.objects.all().delete()
        addon.force_enable(skip_activity_log=True)
        assert addon.status == amo.STATUS_APPROVED
        assert not ActivityLog.objects.exists()

    def test_get_icon_dir_and_path(self):
        assert Addon(pk=4815162342).get_icon_dir().endswith('addon_icons/4815162')
        assert (
            Addon(pk=4815162342)
            .get_icon_path('whatever')
            .endswith('addon_icons/4815162/4815162342-whatever.png')
        )

    def test_icon_url(self):
        """
        Tests for various icons.
        1. Test for an icon that is set.
        2. Test for an icon that is set, with an icon hash
        3. Test for default THEME icon.
        4. Test for default non-THEME icon.
        """
        addon = Addon.objects.get(pk=3615)
        assert addon.get_icon_url(32).endswith('/3/3615-32.png?modified=1275037317')

        addon.icon_hash = 'somehash'
        assert addon.get_icon_url(32).endswith('/3/3615-32.png?modified=somehash')

        addon = Addon.objects.get(pk=3615)
        addon.icon_type = None
        assert (
            addon.get_icon_url(32)
            == 'http://testserver/static/img/addon-icons/default-32.png'
        )

    def test_icon_url_default(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(icon_type='')
        # In prod there would be some cachebusting because we're using
        # staticfiles's storage url() method, but in tests where we don't run
        # collectstatic first that is not the case.
        assert (
            addon.get_icon_url(32)
            == 'http://testserver/static/img/addon-icons/default-32.png'
        )
        assert (
            addon.get_icon_url(64)
            == 'http://testserver/static/img/addon-icons/default-64.png'
        )

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

    def newlines_helper(self, string_before):
        addon = Addon.objects.get(pk=3615)
        addon.privacy_policy = string_before
        addon.save()
        return addon.privacy_policy.localized_string_clean

    def test_newlines(self):
        before = (
            'Paragraph one.\n'
            'This should be on the very next line.\n\n'
            "Should be two nl's before this line.\n\n\n"
            "Should be two nl's before this line.\n\n\n\n"
            "Should be two nl's before this line."
        )

        # Markdown treats multiple blank lines as one.
        after = (
            'Paragraph one.\n'
            'This should be on the very next line.\n\n'
            "Should be two nl's before this line.\n\n"
            "Should be two nl's before this line.\n\n"
            "Should be two nl's before this line."
        )

        assert self.newlines_helper(before) == after

    @patch('olympia.amo.templatetags.jinja_helpers.urlresolvers.get_outgoing_url')
    def test_link_markdown(self, mock_get_outgoing_url):
        mock_get_outgoing_url.return_value = 'https://www.mozilla.org'
        before = 'Heres a link [to here!](https://www.mozilla.org "Click me!")'

        after = (
            'Heres a link '
            '<a href="https://www.mozilla.org" '
            'title="Click me!" rel="nofollow">'
            'to here!'
            '</a>'
        )

        assert self.newlines_helper(before) == after

    def test_abbr_markdown(self):
        before = (
            'TGIF ROFL\n\n*[TGIF]:i stand for this\n\n*[ROFL]: i stand for that\n\n'
        )
        after = (
            '<abbr title="i stand for this">TGIF</abbr> '
            '<abbr title="i stand for that">ROFL</abbr>'
        )

        assert self.newlines_helper(before) == after

    def test_bold_markdown(self):
        before = "Line.\n\n__This line is bold.__\n\n**So is this.**\n\nThis isn't."
        after = (
            'Line.\n\n<strong>This line is bold.</strong>\n\n'
            "<strong>So is this.</strong>\n\nThis isn't."
        )

        assert self.newlines_helper(before) == after

    def test_italics_markdown(self):
        before = "Line.\n\n_This line is emphasized._\n\n*So is this.*\n\nThis isn't."
        after = (
            'Line.\n\n<em>This line is emphasized.</em>\n\n'
            "<em>So is this.</em>\n\nThis isn't."
        )

        assert self.newlines_helper(before) == after

    def test_empty_markdown(self):
        before = 'This is a **** test!'
        after = before

        assert self.newlines_helper(before) == after

    def test_nested_newline(self):
        # Nested newlines escape the markdown.
        before = '**\nThis line is not bold.\n\n*This is italic***'
        after = '**\nThis line is not bold.\n\n<em>This is italic</em>**'

        assert self.newlines_helper(before) == after

    def test_code_markdown(self):
        before = (
            '````'
            'System.out.println("Hello, World!")'
            '````\n\n'
            '    System.out.println("Hello Again!")'
        )

        after = (
            '<code>System.out.println("Hello, World!")</code>\n\n'
            '<code>System.out.println("Hello Again!")\n</code>'
        )

        assert self.newlines_helper(before) == after

    def test_blockquote_markdown(self):
        before = 'Test.\n\n> \n> -  \n\ntest.'
        after = 'Test.\n<blockquote><ul><li></li></ul></blockquote>\ntest.'

        assert self.newlines_helper(before) == after

    def test_ul_markdown(self):
        before = '* \nxx'
        after = '<ul><li>xx</li></ul>'
        assert self.newlines_helper(before) == after

        before = '* xx'
        after = '<ul><li>xx</li></ul>'
        assert self.newlines_helper(before) == after

        before = '* xx\nxx'
        after = '<ul><li>xx\nxx</li></ul>'
        assert self.newlines_helper(before) == after

        before = '*'
        after = before  # Doesn't do anything on its own
        assert self.newlines_helper(before) == after

        # All together now
        before = '* \nxx\n* xx\n* \n* xx\nxx\n'

        after = '<ul><li>xx</li><li>xx</li><li></li><li>xx\nxx</li></ul>'
        assert self.newlines_helper(before) == after

    def test_ol_markdown(self):
        before = '1. \nxx'
        after = '<ol><li>xx</li></ol>'
        assert self.newlines_helper(before) == after

        before = '1. xx'
        after = '<ol><li>xx</li></ol>'
        assert self.newlines_helper(before) == after

        before = '1. xx\nxx'
        after = '<ol><li>xx\nxx</li></ol>'
        assert self.newlines_helper(before) == after

        before = '1.'
        after = before  # Doesn't do anything on its own
        assert self.newlines_helper(before) == after

        # All together now
        before = '1. \nxx\n2. xx\n3. \n4. xx\nxx\n'

        after = '<ol><li>xx</li><li>xx</li><li></li><li>xx\nxx</li></ol>'
        assert self.newlines_helper(before) == after

    def test_newlines_xss_script(self):
        before = "<script>\n\nalert('test');\n</script>"
        after = "&lt;script&gt;\n\nalert('test');\n&lt;/script&gt;"

        assert self.newlines_helper(before) == after

    def test_newlines_xss_inline(self):
        before = '<b onclick="alert(\'test\');">test</b>'
        after = '&lt;b onclick="alert(\'test\');"&gt;test&lt;/b&gt;'

        assert self.newlines_helper(before) == after

    @patch('olympia.amo.templatetags.jinja_helpers.urlresolvers.get_outgoing_url')
    def test_newlines_attribute_link_doublequote(self, mock_get_outgoing_url):
        mock_get_outgoing_url.return_value = 'http://google.com'
        before = '<a href="http://google.com">test</a>'

        parsed = self.newlines_helper(before)

        assert 'rel="nofollow"' in parsed

    def test_newlines_tag(self):
        # user-inputted HTML is cleaned and ignored in favour of markdown.
        # Disallowed markdown is stripped from the final result.
        before = 'This is a <b>bold</b> **test!** \n\n --- \n\n'
        after = 'This is a &lt;b&gt;bold&lt;/b&gt; <strong>test!</strong>'

        assert self.newlines_helper(before) == after

    def test_newlines_unclosed_tag(self):
        before = '<b>test'
        after = '&lt;b&gt;test'

        assert self.newlines_helper(before) == after

    def test_newlines_malformed_faketag(self):
        before = '<madonna'
        after = '&lt;madonna'

        assert self.newlines_helper(before) == after

    def test_newlines_correct_faketag(self):
        before = '<madonna>'
        after = '&lt;madonna&gt;'

        assert self.newlines_helper(before) == after

    def test_newlines_malformed_tag(self):
        before = '<strong'
        after = '&lt;strong'

        assert self.newlines_helper(before) == after

    def test_newlines_malformed_faketag_surrounded(self):
        before = 'This is a <test of bleach'
        after = 'This is a'
        assert self.newlines_helper(before) == after

    def test_newlines_malformed_tag_surrounded(self):
        before = 'This is a <strong of bleach'
        after = 'This is a'
        assert self.newlines_helper(before) == after

    def test_newlines_less_than(self):
        before = '3 < 5'
        after = '3 &lt; 5'

        assert self.newlines_helper(before) == after

    def test_newlines_less_than_tight(self):
        before = 'abc 3<5 def'
        after = 'abc 3&lt;5 def'

        assert self.newlines_helper(before) == after

    def test_review_replies(self):
        """
        Make sure that developer replies are not returned as if they were
        original reviews.
        """
        addon = Addon.objects.get(id=3615)
        u = UserProfile.objects.get(pk=999)
        version = addon.current_version
        new_rating = Rating(
            version=version, user=u, rating=2, body='hello', addon=addon
        )
        new_rating.save()
        new_reply = Rating(
            version=version,
            user=addon.authors.all()[0],
            addon=addon,
            reply_to=new_rating,
            rating=2,
            body='my reply',
        )
        new_reply.save()

        review_list = [rating.pk for rating in addon.ratings]

        assert new_rating.pk in review_list, (
            'Original review must show up in review list.'
        )
        assert new_reply.pk not in review_list, (
            'Developer reply must not show up in review list.'
        )

    def test_update_logs(self):
        addon = Addon.objects.get(id=3615)
        core.set_user(UserProfile.objects.all()[0])
        addon.versions.all().delete()

        entries = ActivityLog.objects.all()
        assert entries[0].action == amo.LOG.CHANGE_STATUS.id

    def setup_files(self, status):
        addon = Addon.objects.create(type=1)
        version = Version.objects.create(addon=addon)
        File.objects.create(status=status, version=version, manifest_version=2)
        return addon, version

    def test_disabled_by_user_disables_listed_versions_waiting_for_review(self):
        addon, version = self.setup_files(amo.STATUS_AWAITING_REVIEW)
        addon.update(status=amo.STATUS_APPROVED)
        addon.update(disabled_by_user=True)
        version.save()
        file_ = version.file
        file_.reload()
        assert version.file.status == amo.STATUS_DISABLED
        assert version.file.original_status == amo.STATUS_AWAITING_REVIEW
        assert (
            version.file.status_disabled_reason
            == File.STATUS_DISABLED_REASONS.DEVELOPER
        )
        assert addon.status == amo.STATUS_NULL
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

    def test_can_request_review_rejected(self):
        addon = Addon.objects.get(pk=3615)
        latest_version = addon.find_latest_version(amo.CHANNEL_LISTED)
        latest_version.update(human_review_date=datetime.now())
        latest_version.file.update(status=amo.STATUS_DISABLED)
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
            amo.STATUS_NULL, False, extra_update_kw={'disabled_by_user': True}
        )

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
        addon.delete(msg='so long and thanks for all the fish')
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

    def test_category_transform(self):
        addon = Addon.objects.get(id=3615)
        assert addon.all_categories[0] in CATEGORIES[addon.type].values()

    def test_can_submit_listed_versions(self):
        addon = Addon.objects.get(id=3615)
        assert addon.can_submit_listed_versions()

        addon.update(status=amo.STATUS_REJECTED)
        assert not addon.can_submit_listed_versions()

    def test_can_submit_listed_versions_deleted(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_DELETED)
        assert not addon.can_submit_listed_versions()

    def test_can_submit_listed_versions_disabled(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_DISABLED)
        assert not addon.can_submit_listed_versions()

        addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        assert not addon.can_submit_listed_versions()

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
        assert addon.has_complete_metadata(has_listed_versions=False)

    def test_listed_has_complete_metadata_no_name(self):
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Confirm complete already.

        delete_translation(addon, 'name')
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        assert addon.has_complete_metadata(has_listed_versions=False)

    def test_listed_has_complete_metadata_no_license(self):
        addon = Addon.objects.get(id=3615)
        assert addon.has_complete_metadata()  # Confirm complete already.

        addon.current_version.update(license=None)
        addon = Addon.objects.get(id=3615)
        assert not addon.has_complete_metadata()
        assert addon.has_complete_metadata(has_listed_versions=False)

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

    def test_auto_approval_disabled_unlisted_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_disabled_unlisted is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.auto_approval_disabled_unlisted is None
        assert addon.auto_approval_disabled_unlisted is None
        # Flag present, value is True: True.
        flags.update(auto_approval_disabled_unlisted=True)
        assert addon.auto_approval_disabled_unlisted is True
        # Flag present, value is False: False.
        flags.update(auto_approval_disabled_unlisted=False)
        assert addon.auto_approval_disabled_unlisted is False

    def test_auto_approval_disabled_until_next_approval_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_disabled_until_next_approval is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.auto_approval_disabled_until_next_approval is None
        assert addon.auto_approval_disabled_until_next_approval is None
        # Flag present, value is True: True.
        flags.update(auto_approval_disabled_until_next_approval=True)
        assert addon.auto_approval_disabled_until_next_approval is True
        # Flag present, value is False: False.
        flags.update(auto_approval_disabled_until_next_approval=False)
        assert addon.auto_approval_disabled_until_next_approval is False

    def test_auto_approval_disabled_until_next_approval_unlisted_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_disabled_until_next_approval_unlisted is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.auto_approval_disabled_until_next_approval_unlisted is None
        assert addon.auto_approval_disabled_until_next_approval_unlisted is None
        # Flag present, value is True: True.
        flags.update(auto_approval_disabled_until_next_approval_unlisted=True)
        assert addon.auto_approval_disabled_until_next_approval_unlisted is True
        # Flag present, value is False: False.
        flags.update(auto_approval_disabled_until_next_approval_unlisted=False)
        assert addon.auto_approval_disabled_until_next_approval_unlisted is False

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

    def test_auto_approval_delayed_until_unlisted_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_delayed_until_unlisted is None
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert flags.auto_approval_delayed_until_unlisted is None
        assert addon.auto_approval_delayed_until_unlisted is None
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(auto_approval_delayed_until_unlisted=in_the_past)
        assert addon.auto_approval_delayed_until_unlisted == in_the_past

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

    def test_auto_approval_delayed_indefinitely_unlisted_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_delayed_indefinitely_unlisted is False
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert addon.auto_approval_delayed_indefinitely_unlisted is False
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(auto_approval_delayed_until_unlisted=in_the_past)
        assert addon.auto_approval_delayed_indefinitely_unlisted is False
        # In the future, but not far enough.
        in_the_future = datetime.now() + timedelta(hours=24)
        flags.update(auto_approval_delayed_until_unlisted=in_the_future)
        assert addon.auto_approval_delayed_indefinitely_unlisted is False
        # This time it's truly delayed indefinitely.
        flags.update(auto_approval_delayed_until_unlisted=datetime.max)
        assert addon.auto_approval_delayed_indefinitely_unlisted is True
        # We only consider the unlisted flag.
        flags.update(
            auto_approval_delayed_until_unlisted=datetime.now(),
            auto_approval_delayed_until=datetime.max,
        )
        assert addon.auto_approval_delayed_indefinitely_unlisted is False
        flags.update(
            auto_approval_delayed_until_unlisted=datetime.max,
            auto_approval_delayed_until=datetime.now(),
        )
        assert addon.auto_approval_delayed_indefinitely_unlisted is True

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
        # Not even if the unlisted flag is set since it's a separate property.
        flags.update(auto_approval_delayed_until_unlisted=in_the_future)
        assert addon.auto_approval_delayed_temporarily is False

    def test_auto_approval_delayed_temporarily_unlisted_property(self):
        addon = Addon.objects.get(pk=3615)
        # No flags: None
        assert addon.auto_approval_delayed_temporarily_unlisted is False
        # Flag present, value is None (default): None.
        flags = AddonReviewerFlags.objects.create(addon=addon)
        assert addon.auto_approval_delayed_temporarily_unlisted is False
        # Flag present, value is a date.
        in_the_past = self.days_ago(1)
        flags.update(auto_approval_delayed_until_unlisted=in_the_past)
        assert addon.auto_approval_delayed_temporarily_unlisted is True
        # Flag present, now properly in the future.
        in_the_future = datetime.now() + timedelta(hours=24)
        flags.update(auto_approval_delayed_until_unlisted=in_the_future)
        assert addon.auto_approval_delayed_temporarily_unlisted is True
        # Not considered temporary any more if it's until the end of time!
        flags.update(auto_approval_delayed_until_unlisted=datetime.max)
        assert addon.auto_approval_delayed_temporarily_unlisted is False
        # Not even if the listed flag is set since it's a separate property.
        flags.update(auto_approval_delayed_until=in_the_future)
        assert addon.auto_approval_delayed_temporarily_unlisted is False

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

    def test_attach_previews(self):
        addons = [
            addon_factory(),
            addon_factory(),
            addon_factory(),
            addon_factory(type=amo.ADDON_STATICTHEME),
        ]
        # Give some of the addons previews:
        # 2 for addons[0]
        pa = Preview.objects.create(addon=addons[0])
        pb = Preview.objects.create(addon=addons[0])
        # nothing for addons[1]; and 1 for addons[2];
        # addons[3] is a theme so doesn't have Preview instances
        pc = Preview.objects.create(addon=addons[2])

        Addon.attach_previews(addons)

        # Create some more previews for [0] and [1].
        # As _current_previews is a cached_property then if attach_previews
        # worked then these new Previews won't be in the cached values.
        Preview.objects.create(addon=addons[0])
        Preview.objects.create(addon=addons[1])
        assert addons[0].current_previews == [pa, pb]
        assert addons[1].current_previews == []
        assert addons[2].current_previews == [pc]
        # But addons[3]'s cached_property shouldn't have been filled with []
        vp = VersionPreview.objects.create(version=addons[3].current_version)
        assert addons[3].current_previews == [vp]

    def test_no_promoted_groups(self):
        addon = addon_factory()
        assert not addon.promoted_groups()
        assert not addon.promoted_groups(currently_approved=False)

    def test_unapproved_promoted_groups(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        assert addon.promoted_groups(currently_approved=False)
        assert not addon.promoted_groups()

    def test_approved_promoted_groups(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        addon.approve_for_version()
        assert addon.promoted_groups()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        # if the group for one approved group changes, its
        # approval for the current version isn't valid,
        # but other groups remain valid
        PromotedAddon.objects.filter(
            addon=addon, promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).update(
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT
            )
        )
        assert (
            PROMOTED_GROUP_CHOICES.SPOTLIGHT
            in addon.promoted_groups(currently_approved=False).group_id
        )
        assert (
            PROMOTED_GROUP_CHOICES.LINE
            in addon.promoted_groups(currently_approved=False).group_id
        )
        assert PROMOTED_GROUP_CHOICES.SPOTLIGHT not in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id

    def test_unapproved_group_after_approval_promoted_groups(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        addon.approve_for_version()
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.NOTABLE)
        assert addon.promoted_groups()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.NOTABLE not in addon.promoted_groups().group_id
        assert (
            PROMOTED_GROUP_CHOICES.NOTABLE
            in addon.promoted_groups(currently_approved=False).group_id
        )
        # Unless approved.
        addon.approve_for_version()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.NOTABLE in addon.promoted_groups().group_id

    def test_application_specific_multiple_promoted_groups(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon,
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            approve_version=True,
        )
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE, approve_version=True
        )
        # Application specific group membership should still work
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        # update to android only
        PromotedAddon.objects.filter(
            addon=addon,
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.LINE,
            application_id=amo.FIREFOX.id,
        ).delete()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id

        # but if there's no approval for Android it's not promoted
        addon.current_version.promoted_versions.filter(
            application_id=amo.ANDROID.id
        ).delete()
        assert PROMOTED_GROUP_CHOICES.RECOMMENDED in addon.promoted_groups().group_id
        assert PROMOTED_GROUP_CHOICES.LINE not in addon.promoted_groups().group_id

    def test_no_promoted(self):
        addon = addon_factory()
        # default case - no group so return None.
        assert addon.publicly_promoted_groups == []

    def test_promoted_groups_doesnt_error_with_no_version(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        addon.current_version.file.update(status=amo.STATUS_DISABLED)
        addon.update_version()
        assert not addon.current_version
        assert not addon.promoted_groups()
        assert addon.promoted_groups(currently_approved=False)

    def test_unapproved_promoted(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        assert addon.publicly_promoted_groups == []

    def test_approved_promoted(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        addon.approve_for_version(addon.current_version)
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
            in addon.publicly_promoted_groups
        )
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            in addon.publicly_promoted_groups
        )
        # If the group changes the approval for that group
        # in the current version isn't valid.
        PromotedAddon.objects.filter(
            addon=addon, promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).update(
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT
            )
        )
        del addon.publicly_promoted_groups
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
            not in addon.publicly_promoted_groups
        )
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            in addon.publicly_promoted_groups
        )

    def test_unapproved_group_after_approval_promoted(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        addon.approve_for_version(addon.current_version)
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            in addon.publicly_promoted_groups
        )
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
            in addon.publicly_promoted_groups
        )
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
            not in addon.publicly_promoted_groups
        )
        # Approving approves them all
        addon.approve_for_version(addon.current_version)
        del addon.publicly_promoted_groups
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            in addon.publicly_promoted_groups
        )
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
            in addon.publicly_promoted_groups
        )
        assert (
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
            in addon.publicly_promoted_groups
        )

    def test_promoted_theme(self):
        recommended = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        addon = addon_factory(type=amo.ADDON_STATICTHEME)
        # default case - no group so return None.
        assert not addon.publicly_promoted_groups

        featured_collection, _ = Collection.objects.get_or_create(
            id=settings.COLLECTION_FEATURED_THEMES_ID
        )
        featured_collection.add_addon(addon)
        del addon.publicly_promoted_groups
        # it's in the collection, so is now promoted.
        assert addon.publicly_promoted_groups
        assert any(
            recommended == promotion for promotion in addon.publicly_promoted_groups
        )

        featured_collection.remove_addon(addon)
        del addon.publicly_promoted_groups
        addon = Addon.objects.get(id=addon.id)
        # but not when it's removed.
        assert not addon.publicly_promoted_groups

    def test_block_property(self):
        addon = Addon.objects.get(id=3615)
        assert addon.block is None

        del addon.block
        block = Block.objects.create(guid=addon.guid, updated_by=user_factory())
        assert addon.block == block

        del addon.block
        block.update(guid='not-a-guid')
        assert addon.block is None

        del addon.block
        addon.delete()
        AddonGUID.objects.create(addon=addon, guid='not-a-guid')
        assert addon.block == block

    def test_blocklistsubmissions_property(self):
        addon = Addon.objects.get(id=3615)
        assert not addon.blocklistsubmissions.exists()

        submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, updated_by=user_factory()
        )
        assert list(addon.blocklistsubmissions) == [submission]

        submission.update(input_guids='not-a-guid')
        submission.update(to_block=[{'guid': 'not-a-guid'}])
        assert not addon.blocklistsubmissions.exists()

        addon.delete()
        AddonGUID.objects.create(addon=addon, guid='not-a-guid')
        assert list(addon.blocklistsubmissions) == [submission]

    def test_can_be_compatible_with_all_fenix_versions_property(self):
        addon = addon_factory()
        assert not addon.can_be_compatible_with_all_fenix_versions

        # It's promoted but nothing has been approved.
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        assert not addon.can_be_compatible_with_all_fenix_versions

        # The latest version is approved.
        addon.approve_for_version(addon.current_version)
        del addon.publicly_promoted_groups
        assert addon.can_be_compatible_with_all_fenix_versions

        addon.promotedaddon.all().delete()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE, apps=[amo.FIREFOX]
        )
        assert not addon.can_be_compatible_with_all_fenix_versions

        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE, apps=[amo.ANDROID]
        )
        assert addon.can_be_compatible_with_all_fenix_versions

    def test_all_approved_applications_for_group_removal_after_approval(self):
        addon = addon_factory()
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        assert addon.all_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        ) == [amo.FIREFOX, amo.ANDROID]
        assert (
            addon.approved_applications_for(
                PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
            )
            == []
        )

        addon.approve_for_version()
        assert addon.all_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        ) == [amo.FIREFOX, amo.ANDROID]
        assert addon.approved_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        ) == [amo.FIREFOX, amo.ANDROID]

        # If an app is removed, it should no longer be in all_apps nor approved
        PromotedAddon.objects.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.LINE,
            application_id=amo.FIREFOX.id,
        ).delete()
        assert addon.all_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        ) == [amo.ANDROID]
        assert addon.approved_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        ) == [amo.ANDROID]

        # Shouldn't affect any other promotion
        assert addon.all_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        ) == [amo.FIREFOX, amo.ANDROID]
        assert addon.approved_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        ) == [amo.FIREFOX, amo.ANDROID]

        # But the approval still exists
        assert PromotedApproval.objects.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.LINE,
            application_id=amo.FIREFOX.id,
        ).exists()

        # And if we add the PromotedAddon back, it should be approved again
        self.make_addon_promoted(addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE)
        assert addon.approved_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        ) == [amo.FIREFOX, amo.ANDROID]

    def test_all_approved_applications_for_group_addition_after_approval(self):
        addon = addon_factory()
        self.make_addon_promoted(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE, apps=[amo.FIREFOX]
        )
        assert addon.all_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        ) == [amo.FIREFOX]
        assert (
            addon.approved_applications_for(
                PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            )
            == []
        )

        # Adding an app after a version should not approve the application
        addon.approve_for_version()
        self.make_addon_promoted(
            addon=addon,
            group_id=PROMOTED_GROUP_CHOICES.LINE,
        )
        assert addon.all_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        ) == [amo.FIREFOX, amo.ANDROID]
        assert addon.approved_applications_for(
            PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        ) == [amo.FIREFOX]

    def test_rollbackable_versions_qs_unavailable(self):
        def get_rvs(channel):
            return list(addon.rollbackable_versions_qs(channel=channel))

        addon = addon_factory()
        version_factory(addon=addon)
        version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)

        with override_switch('version-rollback', active=False):
            assert get_rvs(amo.CHANNEL_LISTED) == []
            assert get_rvs(amo.CHANNEL_UNLISTED) == []

        with override_switch('version-rollback', active=True):
            assert get_rvs(amo.CHANNEL_LISTED) != []
            assert get_rvs(amo.CHANNEL_UNLISTED) != []

            addon.update(type=amo.ADDON_STATICTHEME)
            assert get_rvs(amo.CHANNEL_LISTED) == []
            assert get_rvs(amo.CHANNEL_UNLISTED) == []

    @override_switch('version-rollback', active=True)
    def test_rollbackable_versions_qs(self):
        def get_rvs(channel):
            return list(addon.rollbackable_versions_qs(channel=channel))

        addon = addon_factory()
        assert get_rvs(amo.CHANNEL_LISTED) == []
        assert get_rvs(amo.CHANNEL_UNLISTED) == []

        version1 = addon.current_version
        version2 = version_factory(addon=addon)
        version3 = version_factory(addon=addon)
        assert version3 == addon.reload().current_version
        assert get_rvs(amo.CHANNEL_LISTED) == [version2, version1]
        assert get_rvs(amo.CHANNEL_UNLISTED) == []

        version2.file.update(status=amo.STATUS_DISABLED)
        assert get_rvs(amo.CHANNEL_LISTED) == [version1]
        assert get_rvs(amo.CHANNEL_UNLISTED) == []

        version1.file.update(status=amo.STATUS_DISABLED)
        assert get_rvs(amo.CHANNEL_LISTED) == []
        assert get_rvs(amo.CHANNEL_UNLISTED) == []

        self.make_addon_unlisted(addon)
        File.objects.filter(version__addon=addon).update(status=amo.STATUS_APPROVED)
        assert addon.reload().current_version is None
        assert get_rvs(amo.CHANNEL_LISTED) == []
        assert get_rvs(amo.CHANNEL_UNLISTED) == [version2, version1]

        version2.file.update(status=amo.STATUS_DISABLED)
        assert get_rvs(amo.CHANNEL_LISTED) == []
        assert get_rvs(amo.CHANNEL_UNLISTED) == [version1]

        version1.file.update(status=amo.STATUS_DISABLED)
        assert get_rvs(amo.CHANNEL_LISTED) == []
        assert get_rvs(amo.CHANNEL_UNLISTED) == []

    def test_get_usage_tier(self):
        a_tier = UsageTier.objects.create(upper_adu_threshold=1000)
        b_tier = UsageTier.objects.create(
            lower_adu_threshold=1001, upper_adu_threshold=10000
        )
        c_tier = UsageTier.objects.create(lower_adu_threshold=10001)
        addon = addon_factory(average_daily_users=42)
        assert addon.get_usage_tier() == a_tier
        addon.update(average_daily_users=4242)
        assert addon.get_usage_tier() == b_tier
        addon.update(average_daily_users=424242)
        assert addon.get_usage_tier() == c_tier

    def test_get_usage_tier_edge_cases(self):
        a_tier = UsageTier.objects.create(
            lower_adu_threshold=100, upper_adu_threshold=1000
        )
        addon = addon_factory(average_daily_users=101)
        assert addon.get_usage_tier() == a_tier

        addon.update(type=amo.ADDON_STATICTHEME)
        assert addon.get_usage_tier() is None

        addon.update(status=amo.STATUS_DISABLED, type=amo.ADDON_EXTENSION)
        assert addon.get_usage_tier() is None

        addon.update(status=amo.STATUS_NOMINATED)
        assert addon.get_usage_tier() == a_tier


class TestAddonUser(TestCase):
    def test_delete(self):
        addon = addon_factory()
        user = user_factory()
        addonuser = AddonUser.objects.create(addon=addon, user=user)
        assert AddonUser.objects.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_OWNER
        assert list(addon.authors.all()) == [user]

        addonuser.delete()
        addonuser.reload()
        addon.reload()
        user.reload()

        assert AddonUser.objects.count() == 0
        assert AddonUser.unfiltered.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_DELETED
        assert addonuser.original_role == amo.AUTHOR_ROLE_OWNER
        assert addonuser.addon == addon
        assert addonuser.user == user
        assert user.addons.count() == 0
        assert addon.authors.count() == 0

    def test_delete_dev(self):
        addon = addon_factory()
        user = user_factory()
        addonuser = AddonUser.objects.create(
            addon=addon, user=user, role=amo.AUTHOR_ROLE_DEV
        )
        addonuser.delete()
        addonuser.reload()

        assert AddonUser.objects.count() == 0
        assert AddonUser.unfiltered.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_DELETED
        assert addonuser.original_role == amo.AUTHOR_ROLE_DEV

    def test_delete_queryset(self):
        addon = addon_factory()
        user = user_factory()
        addonuser = AddonUser.objects.create(addon=addon, user=user)
        assert AddonUser.objects.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_OWNER
        assert list(addon.authors.all()) == [user]

        AddonUser.objects.filter(pk=addonuser.pk).delete()
        addonuser.reload()
        addon.reload()
        user.reload()

        assert AddonUser.objects.count() == 0
        assert AddonUser.unfiltered.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_DELETED
        assert addonuser.original_role == amo.AUTHOR_ROLE_OWNER
        assert addonuser.addon == addon
        assert addonuser.user == user
        assert user.addons.count() == 0
        assert addon.authors.count() == 0

    def test_delete_queryset_dev(self):
        addon = addon_factory()
        user = user_factory()
        addonuser = AddonUser.objects.create(
            addon=addon, user=user, role=amo.AUTHOR_ROLE_DEV
        )
        AddonUser.objects.filter(pk=addonuser.pk).delete()
        addonuser.reload()

        assert AddonUser.objects.count() == 0
        assert AddonUser.unfiltered.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_DELETED
        assert addonuser.original_role == amo.AUTHOR_ROLE_DEV

    def test_undelete_queryset(self):
        addon = addon_factory()
        user = user_factory()
        addonuser = AddonUser.objects.create(addon=addon, user=user)

        AddonUser.objects.filter(pk=addonuser.pk).delete()

        assert AddonUser.objects.count() == 0
        assert AddonUser.unfiltered.count() == 1

        AddonUser.unfiltered.filter(pk=addonuser.pk).undelete()
        addonuser.reload()
        addon.reload()
        user.reload()

        assert AddonUser.objects.count() == 1
        assert AddonUser.unfiltered.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_OWNER
        assert addonuser.original_role == amo.AUTHOR_ROLE_DEV  # default value.
        assert addonuser.addon == addon
        assert addonuser.user == user
        assert user.addons.count() == 1
        assert addon.authors.count() == 1

    def test_undelete_queryset_dev(self):
        addon = addon_factory()
        user = user_factory()
        addonuser = AddonUser.objects.create(
            addon=addon, user=user, role=amo.AUTHOR_ROLE_DEV
        )
        AddonUser.objects.filter(pk=addonuser.pk).delete()

        assert AddonUser.objects.count() == 0
        assert AddonUser.unfiltered.count() == 1

        AddonUser.unfiltered.filter(pk=addonuser.pk).undelete()
        addonuser.reload()
        addon.reload()
        user.reload()

        assert AddonUser.objects.count() == 1
        assert AddonUser.unfiltered.count() == 1
        assert addonuser.role == amo.AUTHOR_ROLE_DEV
        assert addonuser.original_role == amo.AUTHOR_ROLE_DEV  # default value.
        assert addonuser.addon == addon
        assert addonuser.user == user
        assert user.addons.count() == 1
        assert addon.authors.count() == 1

    @patch('olympia.scanners.tasks.run_narc_on_version')
    def test_dont_run_narc_waffle_switch_off(self, run_narc_on_version_mock):
        addon = addon_factory(users=[user_factory()])
        addon.addonuser_set.create(user=user_factory())
        assert run_narc_on_version_mock.delay.call_count == 0

    @patch('olympia.scanners.tasks.run_narc_on_version')
    def test_run_narc_new_author(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        addon = addon_factory(users=[user_factory()])
        addon.addonuser_set.create(user=user_factory())
        assert run_narc_on_version_mock.delay.call_count == 1
        assert run_narc_on_version_mock.delay.call_args[0] == (
            addon.current_version.pk,
        )

    @patch('olympia.scanners.tasks.run_narc_on_version')
    def test_run_narc_no_current_version(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        addon = addon_factory(users=[user_factory()])
        version = addon.current_version
        version.is_user_disabled = True
        assert not addon.current_version
        addon.addonuser_set.create(user=user_factory())
        assert run_narc_on_version_mock.delay.call_count == 1
        assert run_narc_on_version_mock.delay.call_args[0] == (version.pk,)

    @patch('olympia.scanners.tasks.run_narc_on_version')
    def test_dont_run_narc_first_author(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        # Note: in "real" situation, the first author would have been added
        # before the first Version, after creating the Addon.
        addon = addon_factory()
        addon.addonuser_set.create(user=user_factory())
        assert run_narc_on_version_mock.delay.call_count == 0

    @patch('olympia.scanners.tasks.run_narc_on_version')
    def test_dont_run_narc_no_listed_version(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        addon = addon_factory(users=[user_factory()])
        self.make_addon_unlisted(addon)
        addon.addonuser_set.create(user=user_factory())
        assert run_narc_on_version_mock.delay.call_count == 0

    @patch('olympia.scanners.tasks.run_narc_on_version')
    def test_dont_run_narc_rejected_listed_version(self, run_narc_on_version_mock):
        self.create_switch('enable-narc', active=True)
        addon = addon_factory(users=[user_factory()])
        addon.current_version.file.update(status=amo.STATUS_DISABLED)
        addon.addonuser_set.create(user=user_factory())
        assert run_narc_on_version_mock.delay.call_count == 0


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

        for version in addon.versions.all():
            version.file.update(status=amo.STATUS_DISABLED)
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
        for _status in status_exc_null:
            assert not addon.should_redirect_to_submit_flow()
        addon.update(status=amo.STATUS_NULL)
        assert addon.should_redirect_to_submit_flow()


class TestHasListedAndUnlistedVersions(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        latest_version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        latest_version.delete(hard=True)
        assert self.addon.versions.count() == 0

    def test_no_versions(self):
        assert not self.addon.has_listed_versions()
        assert not self.addon.has_unlisted_versions()

    def test_listed_version(self):
        version_factory(channel=amo.CHANNEL_LISTED, addon=self.addon)
        assert self.addon.has_listed_versions()
        assert not self.addon.has_unlisted_versions()

    def test_unlisted_version(self):
        version_factory(channel=amo.CHANNEL_UNLISTED, addon=self.addon)
        assert not self.addon.has_listed_versions()
        assert self.addon.has_unlisted_versions()

    def test_unlisted_and_listed_versions(self):
        version_factory(channel=amo.CHANNEL_LISTED, addon=self.addon)
        version_factory(channel=amo.CHANNEL_UNLISTED, addon=self.addon)
        assert self.addon.has_listed_versions()
        assert self.addon.has_unlisted_versions()

    def test_has_listed_versions_current_version_shortcut(self):
        # We shouldn't even do a exists() query if the add-on has a
        # current_version.
        self.addon._current_version_id = 123
        assert self.addon.has_listed_versions()

    def test_has_listed_versions_soft_delete(self):
        version_factory(channel=amo.CHANNEL_LISTED, addon=self.addon, deleted=True)
        version_factory(channel=amo.CHANNEL_UNLISTED, addon=self.addon)
        assert not self.addon.has_listed_versions()
        assert self.addon.has_listed_versions(include_deleted=True)

    def test_has_unlisted_versions_soft_delete(self):
        version_factory(channel=amo.CHANNEL_UNLISTED, addon=self.addon, deleted=True)
        version_factory(channel=amo.CHANNEL_LISTED, addon=self.addon)
        assert not self.addon.has_unlisted_versions()
        assert self.addon.has_unlisted_versions(include_deleted=True)


class TestAddonDueDate(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)

    def test_set_due_date(self):
        addon = Addon.objects.get(id=3615)
        addon.update(status=amo.STATUS_NULL)
        version = addon.versions.latest()
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        version.update(due_date=None)
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        addon.update(status=amo.STATUS_NOMINATED)
        assert version.reload().due_date

    def test_new_version_inherits_due_date(self):
        addon = Addon.objects.get(id=3615)
        old_version = addon.versions.latest()
        addon.update(status=amo.STATUS_NOMINATED)
        old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        NeedsHumanReview.objects.create(
            version=old_version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        old_version.reload()
        assert old_version.due_date
        old_version.update(due_date=self.days_ago(15))
        old_version_due_date = old_version.due_date
        new_version = version_factory(
            addon=addon, version='10.0', file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        NeedsHumanReview.objects.create(
            version=new_version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        assert new_version.reload().due_date == old_version_due_date

    def test_lone_version_does_not_inherit_due_date(self):
        addon = Addon.objects.get(id=3615)
        old_version = addon.versions.latest()
        addon.update(status=amo.STATUS_NOMINATED)
        old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        NeedsHumanReview.objects.create(
            version=old_version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        old_version.reload()
        assert old_version.due_date
        old_version.update(due_date=self.days_ago(15))
        old_version_due_date = old_version.due_date
        Version.objects.all().delete()
        new_version = version_factory(
            addon=addon, version='42.0', file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        NeedsHumanReview.objects.create(
            version=new_version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        new_version.reload()
        assert new_version.due_date
        assert new_version.due_date != old_version_due_date

    def test_reviewed_addon_does_not_inherit_due_date(self):
        addon = Addon.objects.get(id=3615)
        version_number = 10.0
        for status in (amo.STATUS_APPROVED, amo.STATUS_NULL):
            addon.update(status=status)
            version = Version.objects.create(addon=addon, version=str(version_number))
            assert version.due_date is None
            version_number += 1

    def test_due_date_no_version(self):
        # Check that the on_change method still works if there are no versions.
        addon = Addon.objects.get(id=3615)
        addon.versions.all().delete()
        addon.update(status=amo.STATUS_NOMINATED)

    def test_due_date_already_set(self):
        addon = Addon.objects.get(id=3615)
        earlier = datetime.today() - timedelta(days=2)
        version = addon.versions.latest()
        version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        version.update(due_date=earlier)
        addon.update(status=amo.STATUS_NOMINATED)
        assert version.reload().due_date.date() == earlier.date()

    def setup_due_date(
        self, addon_status=amo.STATUS_NOMINATED, file_status=amo.STATUS_AWAITING_REVIEW
    ):
        addon = addon_factory(
            status=addon_status,
            file_kw={'status': file_status},
            version_kw={'version': '0.1'},
            reviewer_flags={'auto_approval_disabled': True},
        )
        version = addon.current_version
        # This would be created by `auto_approve` because of the
        # auto_approval_disabled reviewer flag on the addon.
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        # Cheating date to make sure we don't have a date on the same second
        # the code we test is running.
        past = self.days_ago(1)
        version.update(due_date=past, created=past, modified=past)
        addon.update(status=addon_status)
        due_date = addon.versions.latest().due_date
        assert bool(due_date) == version.should_have_due_date
        return addon, due_date

    def test_due_date_not_reset_if_adding_new_versions(self):
        """
        When the add-on is under initial review (STATUS_NOMINATED), adding new
        versions and files should not reset due date.
        """
        addon, existing_due_date = self.setup_due_date()

        # Adding a new unreviewed version.
        new_version = version_factory(
            addon=addon,
            version='0.2',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # We force the creation of the NHR that would have happened during
        # `auto_approve` like `setup_due_date()` did for the first one.
        NeedsHumanReview.objects.create(
            version=new_version, reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        # Because the add-on is still nominated, the new version should inherit
        # from the existing due date.
        assert new_version.reload().due_date == existing_due_date

        # Adding a new unreviewed version again.
        new_new_version = version_factory(
            addon=addon,
            version='0.3',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # Once again we force the creation of the NHR that would have happened
        # during `auto_approve` like `setup_due_date()` did for the first one.
        NeedsHumanReview.objects.create(
            version=new_new_version,
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED,
        )
        assert new_new_version.reload().due_date == existing_due_date

    def test_new_version_of_approved_addon_should_reset_due_date(self):
        addon, due_date = self.setup_due_date(
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED
        )
        # Now create a new version with an attached file, and update status.
        version = Version.objects.create(addon=addon, version='0.2')
        assert version.due_date is None
        File.objects.create(
            status=amo.STATUS_AWAITING_REVIEW, version=version, manifest_version=2
        )
        assert addon.versions.latest().due_date != due_date

    def _test_set_needs_human_review_on_latest_versions(self, *, skip_activity_log):
        addon = Addon.objects.get(id=3615)
        listed_version = version_factory(
            addon=addon, created=self.days_ago(1), file_kw={'is_signed': True}
        )
        unsigned_listed_version = version_factory(
            addon=addon, file_kw={'is_signed': False}
        )
        unlisted_version = version_factory(
            addon=addon,
            created=self.days_ago(1),
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'is_signed': True},
        )
        unsigned_unlisted_version = version_factory(
            addon=addon, channel=amo.CHANNEL_UNLISTED, file_kw={'is_signed': False}
        )
        due_date = datetime.now() + timedelta(hours=42)
        assert addon.set_needs_human_review_on_latest_versions(
            due_date=due_date,
            reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP,
            skip_activity_log=skip_activity_log,
        ) == [listed_version, unlisted_version]
        for version in [listed_version, unlisted_version]:
            assert version.needshumanreview_set.filter(is_active=True).count() == 1
            assert (
                version.needshumanreview_set.get().reason
                == NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP
            )
        for version in [unsigned_listed_version, unsigned_unlisted_version]:
            # Those are more recent but unsigned, so we don't consider them
            # when figuring out which version to flag for human review.
            assert version.needshumanreview_set.filter(is_active=True).count() == 0

    def test_set_needs_human_review_on_latest_versions_with_log(self):
        self._test_set_needs_human_review_on_latest_versions(skip_activity_log=False)
        assert ActivityLog.objects.filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        ).exists()

    def test_set_needs_human_review_on_latest_versions_without_log(self):
        self._test_set_needs_human_review_on_latest_versions(skip_activity_log=True)
        assert not ActivityLog.objects.filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        ).exists()

    def test_set_needs_human_review_on_latest_versions_ignore_already_reviewed(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.update(human_review_date=self.days_ago(1))
        assert (
            addon.set_needs_human_review_on_latest_versions(
                reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP
            )
            == []
        )
        assert version.needshumanreview_set.filter(is_active=True).count() == 0

        assert addon.set_needs_human_review_on_latest_versions(
            reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP,
            ignore_reviewed=False,
        ) == [version]
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert ActivityLog.objects.filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id
        ).get().arguments == [version]

    def test_set_needs_human_review_on_latest_versions_unique_reason(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        NeedsHumanReview.objects.create(
            version=version, reason=NeedsHumanReview.REASONS.SCANNER_ACTION
        )

        assert not addon.set_needs_human_review_on_latest_versions(
            reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP, unique_reason=False
        )
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.SCANNER_ACTION
        )

        assert addon.set_needs_human_review_on_latest_versions(
            reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP, unique_reason=True
        )
        assert version.needshumanreview_set.filter(is_active=True).count() == 2
        assert list(version.needshumanreview_set.values_list('reason', flat=True)) == [
            NeedsHumanReview.REASONS.SCANNER_ACTION,
            NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP,
        ]

    def test_set_needs_human_review_on_latest_versions_even_deleted(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.delete()
        assert addon.set_needs_human_review_on_latest_versions(
            reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.UNKNOWN
        )

    def test_versions_triggering_needs_human_review_inheritance(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        version.needshumanreview_set.create(reason=NeedsHumanReview.REASONS.UNKNOWN)
        version2 = version_factory(addon=addon)
        unlisted_version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        unlisted_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.UNKNOWN
        )
        assert set(
            addon.versions_triggering_needs_human_review_inheritance(amo.CHANNEL_LISTED)
        ) == {version}
        assert set(
            addon.versions_triggering_needs_human_review_inheritance(
                amo.CHANNEL_UNLISTED
            )
        ) == {unlisted_version}

        # Adding any of those NHR should not matter.
        for reason_value in NeedsHumanReview.REASONS.NO_DUE_DATE_INHERITANCE:
            version2.needshumanreview_set.create(reason=reason_value)

        assert set(
            addon.versions_triggering_needs_human_review_inheritance(amo.CHANNEL_LISTED)
        ) == {version}

        # Adding any other NHR should.
        nhr = version2.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        assert set(
            addon.versions_triggering_needs_human_review_inheritance(amo.CHANNEL_LISTED)
        ) == {version, version2}

        # An inactive NHR should not trigger inheritance.
        nhr.update(is_active=False)
        assert set(
            addon.versions_triggering_needs_human_review_inheritance(amo.CHANNEL_LISTED)
        ) == {version}

    def test_update_all_due_dates(self):
        addon = Addon.objects.get(id=3615)
        versions_that_should_have_due_date = [
            version_factory(addon=addon, file_kw={'is_signed': True}),
            version_factory(addon=addon, file_kw={'is_signed': True}),
        ]
        versions_that_should_not_have_due_date = [
            version_factory(addon=addon, file_kw={'is_signed': True}),
            version_factory(addon=addon, file_kw={'is_signed': True}),
        ]
        # For the versions that should ultimately have a due date, start with
        # an inactive NHR, they shouldn't have their due date yet.
        for version in versions_that_should_have_due_date:
            version.needshumanreview_set.create(is_active=False)
        # For the versions that should not, do it the other way around (so at
        # that moment they do have a due date, but they'll soon lose it).
        for version in versions_that_should_not_have_due_date:
            version.needshumanreview_set.create(is_active=True)

        # Update the NHR through a queryset update: that won't trigger
        # post_save so the due date would not be set/unset until we force it.
        NeedsHumanReview.objects.filter(
            version__in=versions_that_should_have_due_date
        ).update(is_active=True)
        NeedsHumanReview.objects.filter(
            version__in=versions_that_should_not_have_due_date
        ).update(is_active=False)

        addon.update_all_due_dates()
        for version in versions_that_should_have_due_date:
            version.reload()
            assert version.due_date
        for version in versions_that_should_not_have_due_date:
            version.reload()
            assert not version.due_date


class TestAddonDelete(TestCase):
    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)

    def test_cascades(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

        AddonCategory.objects.create(addon=addon, category_id=1)
        AddonUser.objects.create(addon=addon, user=UserProfile.objects.create())
        FrozenAddon.objects.create(addon=addon)

        AddonLog.objects.create(
            addon=addon,
            activity_log=ActivityLog.objects.create(
                action=1, user=UserProfile.objects.create()
            ),
        )
        RssKey.objects.create(addon=addon)

        # This should not throw any FK errors if all the cascades work.
        addon.delete()
        # Make sure it was actually a hard delete.
        assert not Addon.unfiltered.filter(pk=addon.pk).exists()

    def test_review_delete(self):
        addon = Addon.objects.create(
            type=amo.ADDON_EXTENSION, status=amo.STATUS_APPROVED
        )

        rating = Rating.objects.create(
            addon=addon, rating=1, body='foo', user=UserProfile.objects.create()
        )

        flag = RatingFlag(rating=rating)

        addon.delete()

        assert Addon.unfiltered.filter(pk=addon.pk).exists()
        assert not Rating.objects.filter(pk=rating.pk).exists()
        assert not RatingFlag.objects.filter(pk=flag.pk).exists()

        assert Rating.unfiltered.filter(pk=rating.pk).exists()
        assert not ActivityLog.objects.filter(action=amo.LOG.DELETE_RATING.id).exists()

    def test_delete_with_deleted_versions(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = Version.objects.create(addon=addon, version='1.0')
        version.delete()
        addon.delete()
        assert Addon.unfiltered.filter(pk=addon.pk).exists()

    def test_delete_soft_blocks_all_versions(self):
        developer = user_factory()
        addon = addon_factory(users=[developer])
        version = addon.current_version
        deleted_version = version_factory(addon=addon, deleted=True)
        hard_blocked_version = version_factory(
            addon=addon, file_kw={'status': amo.STATUS_DISABLED}
        )
        block = Block.objects.create(guid=addon.guid, updated_by=developer)
        BlockVersion.objects.create(block=block, version=hard_blocked_version)

        addon.delete(send_delete_email=False)

        assert Block.objects.count() == 1
        assert set(block.blockversion_set.values_list('version', flat=True)) == {
            version.id,
            deleted_version.id,
            hard_blocked_version.id,
        }
        assert (
            block.blockversion_set.filter(block_type=BlockType.SOFT_BLOCKED).count()
            == 2
        )
        assert (
            hard_blocked_version.blockversion.reload().block_type == BlockType.BLOCKED
        )
        assert len(mail.outbox) == 0


class TestUpdateStatus(TestCase):
    def test_no_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert Addon.objects.get(pk=addon.pk).status == (amo.STATUS_NOMINATED)
        Version.objects.create(addon=addon)
        assert Addon.objects.get(pk=addon.pk).status == (amo.STATUS_NULL)

    def test_no_valid_file_ends_with_NULL(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = Version.objects.create(addon=addon)
        file_ = File.objects.create(
            status=amo.STATUS_AWAITING_REVIEW, version=version, manifest_version=2
        )
        addon.status = amo.STATUS_NOMINATED
        addon.save()
        assert Addon.objects.get(pk=addon.pk).status == (amo.STATUS_NOMINATED)
        file_.status = amo.STATUS_DISABLED
        file_.save()
        assert Addon.objects.get(pk=addon.pk).status == (amo.STATUS_NULL)

    def test_unlisted_versions_ignored(self):
        addon = addon_factory(status=amo.STATUS_APPROVED)
        addon.update_status()
        assert Addon.objects.get(pk=addon.pk).status == (amo.STATUS_APPROVED)

        addon.current_version.update(channel=amo.CHANNEL_UNLISTED)
        # update_status will have been called via versions.models.update_status
        assert Addon.objects.get(pk=addon.pk).status == (
            amo.STATUS_NULL
        )  # No listed versions so now NULL

    def test_approved_versions_ends_with_approved_addon(self):
        addon = addon_factory(
            status=amo.STATUS_NULL, file_kw={'status': amo.STATUS_DISABLED}
        )
        assert addon.status == amo.STATUS_NULL

        version_factory(addon=addon, file_kw={'status': amo.STATUS_APPROVED})
        addon.reload()
        assert addon.status == amo.STATUS_APPROVED

    def test_awaiting_review_versions_ends_with_nominated(self):
        addon = addon_factory(
            status=amo.STATUS_NULL,
            summary=None,
            file_kw={'status': amo.STATUS_DISABLED},
        )
        assert addon.status == amo.STATUS_NULL

        version_factory(addon=addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        addon.reload()
        # Because it doesn't have complete metadata the status isn't changed
        assert not addon.has_complete_metadata(), addon.get_required_metadata()
        addon.update_status()
        assert addon.status == amo.STATUS_NULL

        addon.summary = 'addon summary'
        addon.save()
        assert addon.has_complete_metadata(), addon.get_required_metadata()
        addon.update_status()
        assert addon.status == amo.STATUS_NOMINATED

    def test_disabled_addons_do_not_update(self):
        addon = addon_factory(
            status=amo.STATUS_DISABLED, file_kw={'status': amo.STATUS_DISABLED}
        )
        assert addon.status == amo.STATUS_DISABLED

        version_factory(addon=addon, file_kw={'status': amo.STATUS_APPROVED})
        addon.reload()
        addon.update_status()
        assert addon.status == amo.STATUS_DISABLED

        version_factory(addon=addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        addon.reload()
        addon.update_status()
        assert addon.status == amo.STATUS_DISABLED

    def test_rejected_listing_addons_do_not_update(self):
        addon = addon_factory(
            status=amo.STATUS_REJECTED, file_kw={'status': amo.STATUS_DISABLED}
        )
        AddonApprovalsCounter.objects.create(
            addon=addon, last_content_review_pass=False
        )
        assert addon.status == amo.STATUS_REJECTED

        version_factory(addon=addon, file_kw={'status': amo.STATUS_APPROVED})
        addon.reload()
        addon.update_status()
        assert addon.status == amo.STATUS_REJECTED

        version_factory(addon=addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        addon.reload()
        addon.update_status()
        assert addon.status == amo.STATUS_REJECTED

        # but if the content review passed, the status will update
        AddonApprovalsCounter.objects.get(addon=addon).update(
            last_content_review_pass=True
        )
        addon.update_status()
        assert addon.status == amo.STATUS_APPROVED


class TestGetVersion(TestCase):
    fixtures = [
        'base/addon_3615',
    ]

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version

    def test_public_new_public_version(self):
        new_version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_APPROVED}
        )
        assert self.addon.find_latest_public_listed_version() == new_version

    def test_public_new_unreviewed_version(self):
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        assert self.addon.find_latest_public_listed_version() == self.version

    def test_should_promote_previous_valid_version_if_latest_is_disabled(self):
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        assert self.addon.find_latest_public_listed_version() == self.version

    def test_should_be_listed(self):
        new_version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_APPROVED},
        )
        assert new_version != self.version
        # Since the new version is unlisted, find_latest_public_listed_version
        # should still find the current one.
        assert self.addon.find_latest_public_listed_version() == self.version

    def test_find_latest_non_rejected_listed_version(self):
        assert (
            self.addon.find_latest_non_rejected_listed_version()
            == self.addon.current_version
        )

        new_version = version_factory(addon=self.addon)
        assert self.addon.find_latest_non_rejected_listed_version() == new_version

        new_version.is_user_disabled = True  # auto-saves
        # No change
        assert self.addon.find_latest_non_rejected_listed_version() == new_version

        # If the version is rejected though, we skip it.
        new_version.file.update(
            status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE
        )
        assert self.addon.find_latest_non_rejected_listed_version() == self.version

    def test_find_latest_non_rejected_listed_version_no_deleted(self):
        self.version.delete()
        assert self.addon.find_latest_non_rejected_listed_version() is None

    def test_find_latest_non_rejected_listed_version_no_listed(self):
        self.make_addon_unlisted(self.addon)
        assert self.addon.find_latest_non_rejected_listed_version() is None


class TestAddonGetURLPath(TestCase):
    def test_get_url_path(self):
        addon = addon_factory(slug='woo')
        assert addon.get_url_path() == '/en-US/firefox/addon/woo/'

    def test_unlisted_addon_get_url_path(self):
        addon = addon_factory(slug='woo', version_kw={'channel': amo.CHANNEL_UNLISTED})
        assert addon.get_url_path() == ''


class TestBackupVersion(TestCase):
    fixtures = ['addons/update', 'base/appversion']

    def setUp(self):
        super().setUp()
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
        version.update(channel=amo.CHANNEL_UNLISTED)
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


class TestPreviewModel(BasePreviewMixin, TestCase):
    fixtures = ['base/previews']

    def get_object(self):
        return Preview.objects.get(pk=24)

    def test_filename(self):
        preview = self.get_object()
        assert preview.thumbnail_path.endswith('.jpg')
        assert preview.image_path.endswith('.png')
        assert preview.original_path.endswith('.png')

        # now set the format in .sizes. Set thumbnail_format to a weird one
        # on purpose to make sure it's followed.
        preview.update(sizes={'thumbnail_format': 'abc', 'image_format': 'gif'})
        assert preview.thumbnail_path.endswith('.abc')
        assert preview.image_path.endswith('.gif')
        assert preview.original_path.endswith('.png')

    def test_filename_in_url(self):
        preview = self.get_object()
        assert '.jpg?modified=' in preview.thumbnail_url
        assert '.png?modified=' in preview.image_url

        # now set the format in .sizes.
        preview.update(sizes={'thumbnail_format': 'abc', 'image_format': 'gif'})
        assert '.abc?modified=' in preview.thumbnail_url
        assert '.gif?modified=' in preview.image_url


class TestListedAddonTwoVersions(TestCase):
    fixtures = ['addons/listed-two-versions']

    def test_listed_two_versions(self):
        Addon.objects.get(id=2795)  # bug 563967


class TestAddonFromUpload(UploadMixin, TestCase):
    fixtures = ['base/users']

    @classmethod
    def setUpTestData(self):
        versions = {
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            AppVersion.objects.get_or_create(
                application=amo.FIREFOX.id, version=version
            )
            AppVersion.objects.get_or_create(
                application=amo.ANDROID.id, version=version
            )

    def setUp(self):
        super().setUp()
        self.selected_app = amo.FIREFOX.id
        self.user = UserProfile.objects.get(pk=999)
        self.user.update(last_login_ip='127.0.0.10')
        self.addCleanup(translation.deactivate)

        def _app(application):
            return ApplicationsVersions(
                application=application.id,
                min=AppVersion.objects.get(
                    application=application.id,
                    version=amo.DEFAULT_WEBEXT_MIN_VERSION,
                ),
                max=AppVersion.objects.get(application=application.id, version='*'),
            )

        self.dummy_parsed_data = {
            'manifest_version': 2,
            'guid': '@webextension-guid',
            'version': '0.0.1',
            'apps': [_app(amo.FIREFOX)],
        }

    def manifest(self, basename):
        return os.path.join(
            settings.ROOT, 'src', 'olympia', 'devhub', 'tests', 'addons', basename
        )

    def test_denied_guid(self):
        """Add-ons that have been disabled by Mozilla are added to DeniedGuid
        in order to prevent resubmission after deletion"""
        DeniedGuid.objects.create(guid='@webextension-guid')
        with self.assertRaises(forms.ValidationError) as e:
            parse_addon(self.get_upload('webextension.xpi'), user=self.user)
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid(self):
        # Upload addon so we can delete it.
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        deleted = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )
        deleted.update(status=amo.STATUS_APPROVED)
        deleted.delete()
        assert deleted.guid == '@webextension-guid'

        # Now upload the same add-on again (so same guid).
        with self.assertRaises(forms.ValidationError) as e:
            self.upload = self.get_upload('webextension.xpi')
            parse_addon(self.upload, user=self.user)
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_existing_guid_same_author_still_forbidden(self):
        # Upload addon so we can delete it.
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        deleted = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )
        assert AddonGUID.objects.filter(guid='@webextension-guid').count() == 1
        # Claim the add-on.
        AddonUser(addon=deleted, user=self.user).save()
        deleted.update(status=amo.STATUS_APPROVED)
        deleted.delete()
        assert deleted.guid == '@webextension-guid'

        # Now upload the same add-on again (so same guid). We're building
        # parsed_data manually to avoid the ValidationError from parse_addon()
        # because we're interested in the error coming after that.
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = {
            'guid': '@webextension-guid',
            'type': 1,
            'version': '0.0.1',
            'name': 'My WebExtension Addon',
            'summary': 'just a test addon with the manifest.json format',
            'homepage': None,
            'default_locale': None,
            'manifest_version': 2,
            'install_origins': [],
            'apps': [],
            'strict_compatibility': False,
            'is_experiment': False,
            'optional_permissions': [],
            'permissions': [],
            'content_scripts': [],
        }

        with self.assertRaises(IntegrityError):
            Addon.from_upload(
                self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
            )

    def test_xpi_attributes(self):
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )
        assert addon.name == 'My WebExtension Addon'
        assert addon.guid == '@webextension-guid'
        assert addon.type == amo.ADDON_EXTENSION
        assert addon.status == amo.STATUS_NULL
        assert addon.homepage is None
        assert addon.summary == 'just a test addon with the manifest.json format'
        assert addon.description is None
        assert addon.slug == 'my-webextension-addon'

    def test_xpi_version(self):
        addon = Addon.from_upload(
            self.get_upload('webextension.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        version = addon.versions.get()
        assert version.version == '0.0.1'
        assert len(version.compatible_apps.keys()) == 1
        assert list(version.compatible_apps.keys())[0].id == self.selected_app
        assert version.file.status == amo.STATUS_AWAITING_REVIEW

    def test_default_locale(self):
        # Make sure default_locale follows the active translation.
        self.dummy_parsed_data.pop('guid')
        addon = Addon.from_upload(
            self.get_upload('webextension_no_id.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert addon.default_locale == 'en-US'

        translation.activate('es-ES')
        self.dummy_parsed_data.pop('guid')
        addon = Addon.from_upload(
            self.get_upload('webextension_no_id.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert addon.default_locale == 'es-ES'

    def test_validation_completes(self):
        upload = self.get_upload('webextension.xpi')
        assert not upload.validation_timeout
        addon = Addon.from_upload(
            upload,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not addon.auto_approval_disabled

    def test_validation_timeout(self):
        upload = self.get_upload('webextension.xpi')
        validation = json.loads(upload.validation)
        timeout_message = {
            'id': ['validator', 'unexpected_exception', 'validation_timeout'],
        }
        validation['messages'] = [timeout_message] + validation['messages']
        upload.validation = json.dumps(validation)
        assert upload.validation_timeout
        addon = Addon.from_upload(
            upload,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not addon.auto_approval_disabled

    def test_mozilla_signed(self):
        upload = self.get_upload('webextension.xpi')
        assert not upload.validation_timeout
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        addon = Addon.from_upload(
            upload,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert addon.auto_approval_disabled

    def test_mozilla_signed_langpack(self):
        upload = self.get_upload('webextension.xpi')
        assert not upload.validation_timeout
        self.dummy_parsed_data['is_mozilla_signed_extension'] = True
        self.dummy_parsed_data['type'] = amo.ADDON_LPAPP
        addon = Addon.from_upload(
            upload,
            selected_apps=[self.selected_app],
            parsed_data=self.dummy_parsed_data,
        )
        assert not addon.auto_approval_disabled

    def test_webextension_generate_guid(self):
        self.upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )

        assert addon.guid is not None
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

        # Uploading the same addon without a id works.
        self.upload = self.get_upload('webextension_no_id.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        new_addon = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )
        assert new_addon.guid is not None
        assert new_addon.guid != addon.guid
        assert addon.guid.startswith('{')
        assert addon.guid.endswith('}')

    def test_webextension_reuse_guid(self):
        self.upload = self.get_upload('webextension.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )

        assert addon.guid == '@webextension-guid'

        # Uploading the same addon with pre-existing id fails
        with self.assertRaises(forms.ValidationError) as e:
            self.upload = self.get_upload('webextension.xpi')
            parsed_data = parse_addon(self.upload, user=self.user)
            Addon.from_upload(
                self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
            )
        assert e.exception.messages == ['Duplicate add-on ID found.']

    def test_webextension_resolve_translations(self):
        self.upload = self.get_upload('notify-link-clicks-i18n.xpi')
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'
        assert addon.name == 'Notify link clicks i18n'
        assert addon.summary == ('Shows a notification when the user clicks on links.')

        # Make sure we set the correct slug
        assert addon.slug == 'notify-link-clicks-i18n'

        translation.activate('de')
        addon.reload()
        assert addon.name == 'Meine Beispielerweiterung'
        assert addon.summary == 'Benachrichtigt den Benutzer über Linkklicks'

    def test_webext_resolve_translations_corrects_locale(self):
        """Make sure we correct invalid `default_locale` values"""
        parsed_data = {
            'manifest_version': 2,
            'default_locale': 'sv',
            'guid': 'notify-link-clicks-i18n@notzilla.org',
            'name': '__MSG_extensionName__',
            'type': 1,
            'apps': [],
            'summary': '__MSG_extensionDescription__',
            'version': '1.0',
            'homepage': '...',
        }

        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )

        # Normalized from `sv` to `sv-SE`
        assert addon.default_locale == 'sv-SE'

    def test_webext_resolve_translations_unknown_locale(self):
        """Make sure we use our default language as default
        for invalid locales
        """
        parsed_data = {
            'manifest_version': 2,
            'default_locale': 'xxx',
            'guid': 'notify-link-clicks-i18n@notzilla.org',
            'name': '__MSG_extensionName__',
            'type': 1,
            'apps': [],
            'summary': '__MSG_extensionDescription__',
            'version': '1.0',
            'homepage': '...',
        }

        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'

    def test_webext_resolve_translations_localized_dict_overrides(self):
        """If we have a dict passed as the field value it is already localised so don't
        try to localize further."""
        parsed_data = {
            'manifest_version': 2,
            'default_locale': 'sv',
            'guid': 'notify-link-clicks-i18n@notzilla.org',
            'name': '__MSG_extensionName__',
            'type': 1,
            'apps': [],
            'summary': {'en-US': 'some summary', 'fr': 'some óthér summary'},
            'version': '1.0',
            'homepage': '...',
        }

        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
        )

        # Normalized from `sv` to `sv-SE`
        assert addon.summary == 'some summary'
        with self.activate('fr'):
            addon.reload()
            assert addon.summary == 'some óthér summary'

    def test_activity_log(self):
        # Set current user as the task user, but use an upload that belongs to
        # another, making sure the activity log belongs to them and not the
        # task user.
        core.set_user(UserProfile.objects.get(pk=settings.TASK_USER_ID))
        self.upload = self.get_upload('webextension.xpi', user=self.user)
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.upload, selected_apps=[self.selected_app], parsed_data=parsed_data
        )
        assert addon
        assert (
            ActivityLog.objects.for_addons(addon)
            .filter(action=amo.LOG.CREATE_ADDON.id)
            .count()
            == 1
        )
        log = (
            ActivityLog.objects.for_addons(addon)
            .filter(action=amo.LOG.CREATE_ADDON.id)
            .get()
        )
        assert log.user == self.user

    def test_client_info(self):
        self.upload = self.get_upload('webextension.xpi', user=self.user)
        parsed_data = parse_addon(self.upload, user=self.user)
        addon = Addon.from_upload(
            self.get_upload('notify-link-clicks-i18n.xpi'),
            selected_apps=[self.selected_app],
            parsed_data=parsed_data,
            client_info='Blâh/6',
        )
        assert addon
        provenance = VersionProvenance.objects.get()
        assert provenance.version == addon.current_version
        assert provenance.source == self.upload.source
        assert provenance.client_info == 'Blâh/6'


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
        qs = Translation.objects.filter(localized_string__isnull=False).values_list(
            'locale', flat=True
        )
        assert sorted(qs.filter(id=a.name_id)) == ['en-US']
        assert sorted(qs.filter(id=a.description_id)) == ['en-US', 'he']

    def test_remove_version_locale(self):
        addon = Addon.objects.create(type=amo.ADDON_DICT)
        version = Version.objects.create(addon=addon)
        version.release_notes = {'fr': 'oui'}
        version.save()
        addon.remove_locale('fr')
        assert not (
            Translation.objects.filter(localized_string__isnull=False).values_list(
                'locale', flat=True
            )
        )


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
        assert mock_.call_args[0][0].status == addon.status

    def test_ignore_non_status_changes(self):
        addon = self.create_addon()
        with patch('olympia.addons.models.track_addon_status_change') as mock_:
            addon.update(type=amo.ADDON_DICT)
        assert not mock_.called, f'Unexpected call: {self.mock_incr.call_args}'

    def test_increment_all_addon_statuses(self):
        addon = self.create_addon(status=amo.STATUS_APPROVED)
        with patch('olympia.addons.models.statsd.incr') as mock_incr:
            track_addon_status_change(addon)
        mock_incr.assert_any_call(
            f'addon_status_change.all.status_{amo.STATUS_APPROVED}'
        )


class TestAddonApprovalsCounter(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_increment_existing(self):
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()
        AddonApprovalsCounter.increment_for_addon(self.addon)
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 1
        self.assertCloseToNow(approval_counter.last_human_review)
        self.assertCloseToNow(approval_counter.last_content_review)
        approval_counter.update(
            last_human_review=self.days_ago(100), last_content_review=self.days_ago(100)
        )
        AddonApprovalsCounter.increment_for_addon(self.addon)
        approval_counter.reload()
        assert approval_counter.counter == 2
        self.assertCloseToNow(approval_counter.last_human_review)
        self.assertCloseToNow(approval_counter.last_content_review)

    def test_increment_non_existing(self):
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon, counter=0
        )
        AddonApprovalsCounter.increment_for_addon(self.addon)
        approval_counter.reload()
        assert approval_counter.counter == 1
        self.assertCloseToNow(approval_counter.last_human_review)
        self.assertCloseToNow(approval_counter.last_content_review)

    def test_reset_existing(self):
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon,
            counter=42,
            last_content_review=self.days_ago(60),
            last_human_review=self.days_ago(30),
        )
        AddonApprovalsCounter.reset_for_addon(self.addon)
        approval_counter.reload()
        assert approval_counter.counter == 0
        # Dates were not touched.
        self.assertCloseToNow(approval_counter.last_human_review, now=self.days_ago(30))
        self.assertCloseToNow(
            approval_counter.last_content_review, now=self.days_ago(60)
        )

    def test_reset_non_existing(self):
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()
        AddonApprovalsCounter.reset_for_addon(self.addon)
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 0

    def test_approve_content_non_existing(self):
        assert not AddonApprovalsCounter.objects.filter(addon=self.addon).exists()
        AddonApprovalsCounter.approve_content_for_addon(self.addon)
        approval_counter = AddonApprovalsCounter.objects.get(addon=self.addon)
        assert approval_counter.counter == 0
        assert approval_counter.last_human_review is None
        self.assertCloseToNow(approval_counter.last_content_review)

    def test_approve_content_existing(self):
        approval_counter = AddonApprovalsCounter.objects.create(
            addon=self.addon,
            counter=42,
            last_content_review=self.days_ago(367),
            last_human_review=self.days_ago(10),
        )
        AddonApprovalsCounter.approve_content_for_addon(self.addon)
        approval_counter.reload()
        # This was updated to now.
        self.assertCloseToNow(approval_counter.last_content_review)
        # Those fields were not touched.
        assert approval_counter.counter == 42
        self.assertCloseToNow(approval_counter.last_human_review, now=self.days_ago(10))


class TestMigratedLWTModel(TestCase):
    def setUp(self):
        self.static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        MigratedLWT.objects.create(
            lightweight_theme_id=666, getpersonas_id=999, static_theme=self.static_theme
        )

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
        with pytest.raises(GuidAlreadyDeniedError) as exc_info:
            addon.deny_resubmission()
        # Exception raised is also a child of the more generic RuntimeError.
        assert isinstance(exc_info.value, RuntimeError)

    def test_deny_empty_guid(self):
        addon = addon_factory(guid=None)
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


class TestExtensionsQueues(TestCase):
    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)

    def test_pending_queue(self):
        expected_addons = [
            addon_factory(
                name='Listed with auto-approval disabled',
                status=amo.STATUS_NOMINATED,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                reviewer_flags={
                    'auto_approval_disabled': True,
                },
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
            ),
            addon_factory(
                name='Pure unlisted with auto-approval disabled',
                status=amo.STATUS_NULL,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                version_kw={'channel': amo.CHANNEL_UNLISTED},
                reviewer_flags={
                    'auto_approval_disabled_unlisted': True,
                },
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
            ),
            version_factory(
                addon=addon_factory(
                    name='Mixed with auto-approval disabled for unlisted',
                    reviewer_flags={
                        'auto_approval_disabled_unlisted': True,
                    },
                ),
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
                channel=amo.CHANNEL_UNLISTED,
            ).addon,
            version_factory(
                addon=version_factory(
                    addon=(
                        addon_mixed_with_both_awaiting_review := addon_factory(
                            name='Mixed with both channel awaiting review',
                            reviewer_flags={
                                'auto_approval_disabled_unlisted': True,
                                'auto_approval_disabled': True,
                            },
                        )
                    ),
                    file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                    needshumanreview_kw={
                        'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                    },
                    channel=amo.CHANNEL_UNLISTED,
                    due_date=datetime.now() + timedelta(hours=24),
                ).addon,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
                due_date=datetime.now() + timedelta(hours=48),
            ).addon,
            version_factory(
                addon=addon_factory(
                    name='Listed already public with auto-approval disabled',
                    reviewer_flags={'auto_approval_disabled': True},
                ),
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
            ).addon,
            version_factory(
                addon=version_factory(
                    addon=(
                        addon_auto_approval_delayed_for_listed := addon_factory(
                            name='Auto-approval delayed for listed, disabled for '
                            'unlisted',
                            reviewer_flags={
                                'auto_approval_delayed_until': datetime.now()
                                + timedelta(hours=24),
                                'auto_approval_disabled_unlisted': True,
                            },
                        )
                    ),
                    file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                    needshumanreview_kw={
                        'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                    },
                    channel=amo.CHANNEL_UNLISTED,
                    due_date=datetime.now() + timedelta(hours=24),
                ).addon,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
                due_date=datetime.now() + timedelta(hours=48),
            ).addon,
            version_factory(
                addon=version_factory(
                    addon=(
                        addon_auto_approval_delayed_for_unlisted := addon_factory(
                            name='Auto-approval delayed for unlisted, disabled for '
                            'listed',
                            reviewer_flags={
                                'auto_approval_delayed_until_unlisted': datetime.now()
                                + timedelta(hours=24),
                                'auto_approval_disabled': True,
                            },
                        )
                    ),
                    file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                    needshumanreview_kw={
                        'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                    },
                    due_date=datetime.now() + timedelta(hours=24),
                    channel=amo.CHANNEL_UNLISTED,
                ).addon,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
                due_date=datetime.now() + timedelta(hours=48),
            ).addon,
        ]
        deleted_addon_human_review = addon_factory(
            name='Deleted add-on - human review',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW, 'is_signed': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        deleted_addon_human_review.delete()
        expected_addons.append(deleted_addon_human_review)
        deleted_unlisted_version_human_review = addon_factory(
            name='Deleted unlisted version - human review',
            version_kw={'channel': amo.CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW, 'is_signed': True},
            reviewer_flags={'auto_approval_disabled_unlisted': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        deleted_unlisted_version_human_review.versions.all()[0].delete()
        expected_addons.append(deleted_unlisted_version_human_review)
        deleted_listed_version_human_review = addon_factory(
            name='Deleted listed version - human review',
            version_kw={'channel': amo.CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW, 'is_signed': True},
            reviewer_flags={'auto_approval_disabled': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        deleted_listed_version_human_review.versions.all()[0].delete()
        expected_addons.append(deleted_listed_version_human_review)
        disabled_with_human_review = addon_factory(
            name='Disabled by Mozilla',
            status=amo.STATUS_DISABLED,
            file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        expected_addons.append(disabled_with_human_review)

        # Add add-ons that should not appear. For some it's because of
        # something we're explicitly filtering out, for others it's because of
        # something that causes the factories not to generate a due date for
        # them.
        addon_factory(name='Fully Public Add-on')
        addon_factory(
            name='Pure unlisted',
            status=amo.STATUS_NULL,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        addon_factory(
            name='Add-on that will be auto-approved',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(name='Add-on with version that will be auto-approved'),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        addon_factory(
            name='Theme',
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        addon_factory(
            name='Disabled by Mozilla',
            status=amo.STATUS_DISABLED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED,
                'is_active': False,  # mimics force_disable()
            },
        )
        version_review_flags_factory(
            version=addon_factory(
                name='Pending rejection',
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            ).current_version,
            pending_rejection=datetime.now(),
        )
        addon_factory(
            name='Deleted add-on',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        ).delete()
        addon_factory(
            name='Deleted unlisted version',
            version_kw={'channel': amo.CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled_unlisted': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        ).versions.all()[0].delete()
        addon_factory(
            name='Deleted listed version',
            version_kw={'channel': amo.CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        ).versions.all()[0].delete()

        addons = Addon.unfiltered.get_queryset_for_pending_queues()
        assert list(addons.order_by('pk')) == expected_addons

        # Test that we picked the version with the oldest due date and that we
        # added the first_pending_version property.
        for addon in addons:
            expected_version = (
                addon.versions(manager='unfiltered_for_relations')
                .exclude(due_date=None)
                .order_by('due_date')
                .first()
            )
            assert expected_version
            assert addon.first_pending_version == expected_version

        # If we show only upcoming - short due dates - most of the addons won't be
        # included because our standard review time (3) is longer than the cut off (2)
        addons = Addon.unfiltered.get_queryset_for_pending_queues(
            show_only_upcoming=True
        )
        assert set(addons) == {
            addon_auto_approval_delayed_for_listed,
            addon_auto_approval_delayed_for_unlisted,
            addon_mixed_with_both_awaiting_review,
        }

        addons = Addon.unfiltered.get_queryset_for_pending_queues(
            admin_reviewer=True, show_only_upcoming=True
        )
        due_dates_within_2_days = {
            addon_auto_approval_delayed_for_listed,
            addon_auto_approval_delayed_for_unlisted,
            addon_mixed_with_both_awaiting_review,
        }
        assert set(addons) == due_dates_within_2_days
        # the upcoming days config can be overriden
        set_config(amo.config_keys.UPCOMING_DUE_DATE_CUT_OFF_DAYS, '10')
        addons = Addon.unfiltered.get_queryset_for_pending_queues(
            admin_reviewer=True, show_only_upcoming=True
        )
        assert set(addons) == set(expected_addons)
        # an invalid config value will default back to 2 again
        set_config(amo.config_keys.UPCOMING_DUE_DATE_CUT_OFF_DAYS, '10.')
        addons = Addon.unfiltered.get_queryset_for_pending_queues(
            admin_reviewer=True, show_only_upcoming=True
        )
        assert set(addons) == due_dates_within_2_days

        # If we pass show_temporarily_delayed=False, versions in a channel that
        # is temporarily delayed should not be considered. We already have a
        # couple add-ons with versions delayed, but they should show up since
        # they also have a version non-delayed in another channel. Let's add
        # some that shouldn't show up.
        version_factory(
            addon=version_factory(
                addon=addon_factory(
                    name='Auto-approval delayed for unlisted and listed',
                    reviewer_flags={
                        'auto_approval_delayed_until_unlisted': datetime.now()
                        + timedelta(hours=24),
                        'auto_approval_delayed_until': datetime.now()
                        + timedelta(hours=24),
                    },
                ),
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
                channel=amo.CHANNEL_UNLISTED,
            ).addon,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
        )
        addon_factory(
            name='Pure unlisted with auto-approval delayed',
            reviewer_flags={
                'auto_approval_delayed_until_unlisted': datetime.now()
                + timedelta(hours=24),
            },
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            needshumanreview_kw={
                'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
            },
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        addons = Addon.unfiltered.get_queryset_for_pending_queues(
            show_temporarily_delayed=False
        )
        assert set(addons) == set(expected_addons)

    def _test_pending_queue_needs_human_review_from(self, reason, annotated_field):
        nhr_abuse = addon_factory(file_kw={'is_signed': True})
        NeedsHumanReview.objects.create(
            version=nhr_abuse.versions.latest('pk'),
            reason=reason,
        )
        nhr_other = addon_factory(file_kw={'is_signed': True})
        NeedsHumanReview.objects.create(version=nhr_other.versions.latest('pk'))
        nhr_abuse_inactive = addon_factory(file_kw={'is_signed': True})
        NeedsHumanReview.objects.create(
            version=nhr_abuse_inactive.versions.latest('pk'),
            reason=reason,
            is_active=False,
        )
        NeedsHumanReview.objects.create(
            version=nhr_abuse_inactive.versions.latest('pk')
        )
        nhr_without_due_date = addon_factory(file_kw={'is_signed': True})
        NeedsHumanReview.objects.create(
            version=nhr_without_due_date.versions.latest('pk'),
            reason=reason,
        )
        nhr_without_due_date.versions.latest('pk').update(due_date=None)
        NeedsHumanReview.objects.create(
            version=version_factory(
                addon=nhr_without_due_date, file_kw={'is_signed': True}
            )
        )

        addons = {
            addon.id: addon
            for addon in Addon.unfiltered.get_queryset_for_pending_queues()
        }

        assert set(addons.values()) == {
            nhr_abuse,
            nhr_other,
            nhr_without_due_date,
            nhr_abuse_inactive,
        }
        assert getattr(addons[nhr_abuse.id], annotated_field)
        if annotated_field != 'needs_human_review_other':
            assert not getattr(addons[nhr_other.id], annotated_field)
            assert not getattr(addons[nhr_without_due_date.id], annotated_field)
            assert not getattr(addons[nhr_abuse_inactive.id], annotated_field)
        else:
            assert getattr(addons[nhr_other.id], annotated_field)
            assert getattr(addons[nhr_without_due_date.id], annotated_field)
            assert getattr(addons[nhr_abuse_inactive.id], annotated_field)

    def test_pending_queue_needs_human_review_from_abuse(self):
        self._test_pending_queue_needs_human_review_from(
            NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
            'needs_human_review_abuse_addon_violation',
        )

    def test_pending_queue_needs_human_review_from_appeal(self):
        self._test_pending_queue_needs_human_review_from(
            NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL,
            'needs_human_review_addon_review_appeal',
        )

    def test_pending_queue_needs_human_review_from_cinder_forwarded_abuse(self):
        self._test_pending_queue_needs_human_review_from(
            NeedsHumanReview.REASONS.CINDER_ESCALATION,
            'needs_human_review_cinder_escalation',
        )

    def test_pending_queue_needs_human_review_from_cinder_forwarded_appeal(self):
        self._test_pending_queue_needs_human_review_from(
            NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION,
            'needs_human_review_cinder_appeal_escalation',
        )

    def test_pending_queue_needs_human_review_from_2nd_level_approval(self):
        self._test_pending_queue_needs_human_review_from(
            NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE,
            'needs_human_review_second_level_requeue',
        )

    def test_pending_queue_needs_human_scanner_action(self):
        self._test_pending_queue_needs_human_review_from(
            NeedsHumanReview.REASONS.SCANNER_ACTION, 'needs_human_review_scanner_action'
        )

    def test_get_queryset_for_pending_queues_for_specific_due_date_reasons(self):
        expected_addons = [
            version_factory(
                addon=addon_factory(
                    version_kw={
                        'needshumanreview_kw': {
                            'reason': NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
                        },
                        'due_date': self.days_ago(48),
                        'version': '0.1',
                    }
                ),
                needshumanreview_kw={
                    'reason': NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                },
                due_date=self.days_ago(15),
                version='0.2',
            ).addon,
            addon_factory(
                version_kw={
                    'needshumanreview_kw': {
                        'reason': NeedsHumanReview.REASONS.SCANNER_ACTION
                    },
                    'due_date': self.days_ago(16),
                    'version': '666.0',
                }
            ),
        ]
        addon_factory(
            version_kw={
                'needshumanreview_kw': {
                    'reason': NeedsHumanReview.REASONS.DEVELOPER_REPLY
                },
                'due_date': self.days_ago(234),
            }
        )  # Should not show up
        addon_factory(
            version_kw={
                'needshumanreview_kw': {
                    'reason': NeedsHumanReview.REASONS.DEVELOPER_REPLY
                },
                'due_date': self.days_ago(342),
            }
        ).current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.SCANNER_ACTION, is_active=False
        )  # Should not show up either (SCANNER_ACTION NHR is inactive)

        addons = Addon.objects.get_queryset_for_pending_queues(
            due_date_reasons_choices=NeedsHumanReview.REASONS.extract_subset(
                'AUTO_APPROVAL_DISABLED', 'SCANNER_ACTION'
            )
        )
        assert list(addons) == expected_addons
        expected_version = expected_addons[0].versions.get(version='0.2')
        assert addons[0].first_version_id == expected_version.pk
        assert addons[0].first_pending_version == expected_version
        assert addons[0].first_version_due_date == expected_version.due_date

    def test_get_pending_rejection_queue(self):
        expected_addons = [
            version_review_flags_factory(
                version=version_factory(
                    addon=version_review_flags_factory(
                        version=version_factory(addon=addon_factory()),
                        pending_rejection=datetime.now() + timedelta(hours=24),
                    ).version.addon,
                ),
                pending_rejection=datetime.now() + timedelta(hours=48),
            ).version.addon,
        ]
        addon_factory()
        addons = Addon.objects.get_pending_rejection_queue()
        assert set(addons) == set(expected_addons)
        # Test that we picked the version with the oldest due date and that we
        # added the first_pending_version property.
        for addon in addons:
            expected_version = (
                addon.versions(manager='unfiltered_for_relations')
                .filter(reviewerflags__pending_rejection__isnull=False)
                .order_by('reviewerflags__pending_rejection')
                .first()
            )
            assert expected_version
            assert addon.first_pending_version == expected_version


class TestThemesPendingManualApprovalQueue(TestCase):
    def setUp(self):
        user_factory(pk=settings.TASK_USER_ID)

    def test_basic(self):
        expected = [
            addon_factory(
                type=amo.ADDON_STATICTHEME,
                status=amo.STATUS_NOMINATED,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            )
        ]
        addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        qs = Addon.objects.get_queryset_for_pending_queues(theme_review=True).order_by(
            'pk'
        )
        assert list(qs) == expected

    def test_approved_theme_pending_version(self):
        expected = [
            addon_factory(
                type=amo.ADDON_STATICTHEME,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            )
        ]
        disabled_with_human_review = addon_factory(
            name='Disabled by Mozilla',
            status=amo.STATUS_DISABLED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True},
        )
        NeedsHumanReview.objects.create(
            version=disabled_with_human_review.versions.latest('pk')
        )
        expected.append(disabled_with_human_review)
        rejected_version_with_human_review = addon_factory(
            name='rejected version',
            status=amo.STATUS_NULL,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True},
        )
        NeedsHumanReview.objects.create(
            version=rejected_version_with_human_review.versions.latest('pk')
        )
        expected.append(rejected_version_with_human_review)

        addon_factory(
            type=amo.ADDON_STATICTHEME,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        addon_factory(type=amo.ADDON_STATICTHEME)
        addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        qs = (
            Addon.objects.get_queryset_for_pending_queues(theme_review=True)
            .exclude(status=amo.STATUS_NOMINATED)
            .order_by('pk')
        )
        assert list(qs) == expected


class TestAddonGUID(TestCase):
    def test_creates_hashed_guid_on_save(self):
        guid = '@exquisite-sandwich-1'
        expected_hashed_guid = (
            '983e300fe553f61e87adbf2f55be537fe79b0a0da324847ca2712274e2f352d9'
        )

        # This will create the AddonGUID instance.
        addon = addon_factory(guid=guid)

        addon_guid = AddonGUID.objects.get(addon=addon)
        assert addon_guid.hashed_guid == expected_hashed_guid


class TestAddonRegionalRestrictions(TestCase):
    def test_clean(self):
        arr = AddonRegionalRestrictions.objects.create(addon=addon_factory())
        arr.excluded_regions = ['fr']
        arr.clean()
        assert arr.excluded_regions == ['FR']
        arr.excluded_regions = ['FR', 'BR', 'cn']
        arr.clean()
        assert arr.excluded_regions == ['FR', 'BR', 'CN']


class TestAddonListingInfo(TestCase):
    def test_is_listing_noindexed_without_info(self):
        addon = addon_factory()
        # This shouldn't raise any exception.
        assert not addon.is_listing_noindexed

    def test_is_listing_noindexed(self):
        addon = addon_factory()
        # No noindex date set.
        info = AddonListingInfo.objects.create(addon=addon)
        assert not addon.is_listing_noindexed
        # Noindex date set in the past means the listing should not longer be
        # noindexed.
        info.update(noindex_until=datetime.now() - timedelta(days=1))
        assert not addon.is_listing_noindexed
        # Noindex date set after the current date.
        info.update(noindex_until=datetime.now() + timedelta(days=1))
        assert addon.is_listing_noindexed

    def test_maybe_mark_as_noindexed_skipped_for_oldish_addons(self):
        addon = addon_factory(created=self.days_ago(91))
        AddonListingInfo.maybe_mark_as_noindexed(addon)
        assert AddonListingInfo.objects.count() == 0
        assert not addon.is_listing_noindexed

    def test_maybe_mark_as_noindexed_creates_a_record(self):
        addon = addon_factory(created=self.days_ago(1))
        AddonListingInfo.maybe_mark_as_noindexed(addon)
        assert AddonListingInfo.objects.count() == 1
        assert addon.is_listing_noindexed

    def test_maybe_mark_as_noindexed_updates_existing_record(self):
        addon = addon_factory(created=self.days_ago(1))

        AddonListingInfo.maybe_mark_as_noindexed(addon)
        assert AddonListingInfo.objects.count() == 1
        first_date = AddonListingInfo.objects.first().noindex_until
        assert addon.is_listing_noindexed

        AddonListingInfo.maybe_mark_as_noindexed(addon)
        assert AddonListingInfo.objects.count() == 1
        second_date = AddonListingInfo.objects.first().noindex_until
        assert addon.is_listing_noindexed

        # The existing record should have been updated with a newer date.
        assert second_date > first_date
