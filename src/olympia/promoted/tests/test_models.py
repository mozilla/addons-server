from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from olympia import amo, core
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.constants import applications
from olympia.constants.promoted import (
    DEACTIVATED_LEGACY_IDS,
    PROMOTED_GROUP_CHOICES,
    PROMOTED_GROUPS_BY_ID,
)
from olympia.promoted.models import (
    PromotedAddon,
    PromotedAddonPromotion,
    PromotedAddonVersion,
    PromotedApproval,
    PromotedGroup,
)
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.utils import get_review_due_date


class TestPromotedAddon(TestCase):
    def setUp(self):
        self.task_user = user_factory(pk=settings.TASK_USER_ID)

    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=PROMOTED_GROUP_CHOICES.LINE
        )
        assert promoted_addon.group.id == PROMOTED_GROUP_CHOICES.LINE
        assert promoted_addon.application_id is None
        assert promoted_addon.all_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.all_applications == [applications.FIREFOX]

    def test_is_approved_applications(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE
        )
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert addon.promotedaddon.approved_applications == []

        # the current version needs to be approved also
        promoted_addon.approve_for_version(addon.current_version)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        assert addon.promotedaddon.approved_applications == []
        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version,
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            application_id=applications.FIREFOX.id,
        )
        addon.reload()
        assert addon.promotedaddon.approved_applications == [applications.FIREFOX]

        # for promoted groups that don't require pre-review though, there isn't
        # a per version approval, so a current_version is sufficient and all
        # applications are seen as approved.
        promoted_addon.update(group_id=PROMOTED_GROUP_CHOICES.STRATEGIC)
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

    def test_auto_approves_addon_when_saved_for_immediate_approval(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        assert promo.group.id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.immediate_approval == False
        promo.group_id = PROMOTED_GROUP_CHOICES.RECOMMENDED
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED

        # then with a group thats immediate_approval == True
        promo.group_id = PROMOTED_GROUP_CHOICES.SPOTLIGHT
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX]
        assert PromotedApproval.objects.count() == 1
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.SPOTLIGHT

        # test the edge case where the application was changed afterwards
        promo.application_id = 0
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX, amo.ANDROID]
        assert PromotedApproval.objects.count() == 2

    def test_addon_flagged_for_human_review_when_saved(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        listed_ver = promo.addon.current_version
        # throw in an unlisted version too
        unlisted_ver = version_factory(addon=promo.addon, channel=amo.CHANNEL_UNLISTED)
        assert promo.group.id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.flag_for_human_review == False
        promo.group_id = PROMOTED_GROUP_CHOICES.RECOMMENDED
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        assert unlisted_ver.needshumanreview_set.count() == 0
        assert listed_ver.needshumanreview_set.count() == 0

        # then with a group thats flag_for_human_review == True but pretend
        # the version has already been reviewed by a human (so it's not
        # necessary to flag it as needing human review again).
        listed_ver.update(human_review_date=self.days_ago(1))
        unlisted_ver.update(human_review_date=self.days_ago(1))
        listed_ver.file.update(is_signed=True)
        unlisted_ver.file.update(is_signed=True)
        promo.addon.reload()
        promo.group_id = PROMOTED_GROUP_CHOICES.NOTABLE
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        assert not listed_ver.reload().due_date
        assert not unlisted_ver.reload().due_date
        assert unlisted_ver.needshumanreview_set.count() == 0
        assert listed_ver.needshumanreview_set.count() == 0

        # then with a group thats flag_for_human_review == True without the
        # version having been reviewed by a human but not signed: also not
        # flagged.
        listed_ver.update(human_review_date=None)
        unlisted_ver.update(human_review_date=None)
        listed_ver.file.update(is_signed=False)
        unlisted_ver.file.update(is_signed=False)
        promo.addon.reload()
        promo.group_id = PROMOTED_GROUP_CHOICES.NOTABLE
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        assert not listed_ver.reload().due_date
        assert not unlisted_ver.reload().due_date
        assert unlisted_ver.needshumanreview_set.count() == 0
        assert listed_ver.needshumanreview_set.count() == 0

        # then with a group thats flag_for_human_review == True without the
        # version having been reviewed by a human but signed: this time we
        # should flag it.
        listed_ver.file.update(is_signed=True)
        unlisted_ver.file.update(is_signed=True)
        promo.addon.reload()
        promo.group_id = PROMOTED_GROUP_CHOICES.NOTABLE
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        self.assertCloseToNow(listed_ver.reload().due_date, now=get_review_due_date())
        self.assertCloseToNow(unlisted_ver.reload().due_date, now=get_review_due_date())
        assert unlisted_ver.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            unlisted_ver.needshumanreview_set.get().reason
            == unlisted_ver.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert listed_ver.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            listed_ver.needshumanreview_set.get().reason
            == unlisted_ver.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )

    def test_disabled_and_deleted_versions_flagged_for_human_review(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        version = addon.find_latest_version(None, exclude=(), deleted=True)
        promo = PromotedAddon.objects.create(
            addon=addon,
            application_id=amo.FIREFOX.id,
            group_id=PROMOTED_GROUP_CHOICES.NOTABLE,
        )
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        self.assertCloseToNow(version.reload().due_date, now=get_review_due_date())
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )

        # And if deleted too
        version.needshumanreview_set.update(is_active=False)
        version.update(due_date=None)
        version.delete()
        promo.save()
        self.assertCloseToNow(version.reload().due_date, now=get_review_due_date())
        assert version.needshumanreview_set.count() == 2
        needs_human_review = version.needshumanreview_set.latest('pk')
        assert (
            needs_human_review.reason
            == version.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert needs_human_review.is_active

        # even if the add-on is deleted
        version.needshumanreview_set.update(is_active=False)
        version.update(due_date=None)
        addon.delete()
        promo.save()
        self.assertCloseToNow(version.reload().due_date, now=get_review_due_date())
        assert version.needshumanreview_set.count() == 3
        needs_human_review = version.needshumanreview_set.latest('pk')
        assert (
            needs_human_review.reason
            == version.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
        )
        assert needs_human_review.is_active

    def test_approve_for_addon(self):
        core.set_user(user_factory())
        promo = PromotedAddon.objects.create(
            addon=addon_factory(
                version_kw={'version': '0.123a'},
                file_kw={'filename': 'webextension.xpi'},
            ),
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
        )
        # SPOTLIGHT doesnt have special signing states so won't be resigned
        # approve_for_addon is called automatically - SPOTLIGHT has immediate_approval
        promo.addon.reload()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.SPOTLIGHT
        assert promo.addon.current_version.version == '0.123a'


class TestPromotedGroup(TestCase):
    def test_promoted_group_data_is_derived_from_promoted_groups(self):
        # Loop over all groups from PROMOTED_GROUPS_BY_ID to ensure complete coverage
        for const_group in PROMOTED_GROUPS_BY_ID.values():
            try:
                pg = PromotedGroup.objects.get(group_id=const_group.id)
            except PromotedGroup.DoesNotExist:
                self.fail(f'PromotedGroup with id={const_group.id} not found')

            self.assertEqual(pg.name, const_group.name)
            self.assertEqual(pg.api_name, const_group.api_name)
            self.assertAlmostEqual(
                pg.search_ranking_bump, const_group.search_ranking_bump
            )
            self.assertEqual(pg.listed_pre_review, const_group.listed_pre_review)
            self.assertEqual(pg.unlisted_pre_review, const_group.unlisted_pre_review)
            self.assertEqual(pg.admin_review, const_group.admin_review)
            self.assertEqual(pg.badged, const_group.badged)
            self.assertEqual(
                pg.autograph_signing_states, const_group.autograph_signing_states
            )
            self.assertEqual(pg.can_primary_hero, const_group.can_primary_hero)
            self.assertEqual(pg.immediate_approval, const_group.immediate_approval)
            self.assertEqual(
                pg.flag_for_human_review, const_group.flag_for_human_review
            )
            self.assertEqual(
                pg.can_be_compatible_with_all_fenix_versions,
                const_group.can_be_compatible_with_all_fenix_versions,
            )
            self.assertEqual(pg.high_profile, const_group.high_profile)
            self.assertEqual(pg.high_profile_rating, const_group.high_profile_rating)
            expected_active = True
            self.assertEqual(pg.active, expected_active)

    def test_deactived_group_ids_raise(self):
        for group_id in DEACTIVATED_LEGACY_IDS:
            with self.assertRaises(ValidationError):
                PromotedGroup.objects.create(
                    group_id=group_id,
                    name='Test',
                    api_name='test',
                )

    def test_str_method(self):
        # Ensure the __str__ method returns the name
        for const_group in PROMOTED_GROUPS_BY_ID.values():
            pg = PromotedGroup.objects.get(group_id=const_group.id)
            self.assertEqual(str(pg), const_group.name)

    def test_boolean_representation(self):
        promoted_group = PromotedGroup.objects.create(
            group_id=PROMOTED_GROUP_CHOICES.NOT_PROMOTED,
            name='Test',
            api_name='test',
        )
        assert str(promoted_group) == 'Test'
        assert bool(promoted_group) is False

    def test_get_active_or_badged_promoted_groups(self):
        active_groups = PromotedGroup.active_groups()
        assert len(active_groups) == 6
        badged_groups = PromotedGroup.badged_groups()
        assert len(badged_groups) == 2

        for group in PromotedGroup.objects.all():
            if group.active:
                assert group in active_groups
            if group.badged:
                assert group in badged_groups
            if not group.active and not group.badged:
                assert group not in active_groups and group not in badged_groups


class TestPromotedAddonPromotion(TestCase):
    def setUp(self):
        self.addon: Addon = addon_factory()
        self.promoted_group = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT
        )
        self.application_id = applications.FIREFOX.id
        self.required_fields = {
            'addon': self.addon,
            'promoted_group': self.promoted_group,
            'application_id': self.application_id,
        }

    def test_required_fields(self):
        for field in self.required_fields.keys():
            missing_fields = {
                k: v for k, v in self.required_fields.items() if k != field
            }
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    PromotedAddonPromotion.objects.create(**missing_fields)

        assert PromotedAddonPromotion.objects.create(**self.required_fields) is not None

    def test_str_method(self):
        promoted_addon_promotion = PromotedAddonPromotion.objects.create(
            **self.required_fields
        )
        assert str(promoted_addon_promotion) == (
            f'{self.promoted_group.name} - {self.addon} - {applications.FIREFOX.short}'
        )

    def test_immediate_approval(self):
        assert self.promoted_group.immediate_approval

        PromotedAddonPromotion.objects.create(**self.required_fields)
        assert PromotedAddonVersion.objects.count() == 1

    def test_flag_human_review(self):
        # Task user is used for automatic activity logs
        # during creation of needs human review objects.
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        # Create a promoted group that triggers human review.
        promoted_group = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.NOTABLE
        )
        assert promoted_group.flag_for_human_review
        # The addon should be signed so we can flag for human review.
        addon = addon_factory(file_kw={'is_signed': True})

        PromotedAddonPromotion.objects.create(
            addon=addon,
            application_id=self.application_id,
            # Replace the promoted group with one that requires
            # human review before approval.
            promoted_group=promoted_group,
        )
        # We do not create a promoted addon version here because
        # we are waiting for human review of the version.
        assert PromotedAddonVersion.objects.count() == 0
        assert NeedsHumanReview.objects.filter(
            version=addon.current_version,
            reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP,
        ).exists()

    def _test_unique_constraint(self, fields, should_raise=False):
        # Create the original instance to test constraints against
        original = PromotedAddonPromotion.objects.create(**self.required_fields)
        # merge the fields with the required fields
        merged = {**self.required_fields, **fields}
        if should_raise:
            # Should raise while the original instance exists
            with (
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                PromotedAddonPromotion.objects.create(**merged)
            # Delete the original instance to test the constraint
            # is lifted when it is deleted.
            original.delete()

        assert PromotedAddonPromotion.objects.create(**merged) is not None

    def test_multiple_promoted_groups_per_addon_raises(self):
        self._test_unique_constraint(
            {
                'promoted_group': PromotedGroup.objects.get(
                    group_id=PROMOTED_GROUP_CHOICES.NOT_PROMOTED
                ),
            },
            should_raise=True,
        )

    def test_multiple_applications_per_promoted_group_allowed(self):
        self._test_unique_constraint(
            {
                'application_id': applications.ANDROID.id,
            },
            should_raise=False,
        )

    def test_multiple_addons_per_application_group_allowed(self):
        self._test_unique_constraint({'addon': addon_factory()}, should_raise=False)

    def test_pure_duplicate_raises(self):
        self._test_unique_constraint({}, should_raise=True)


class TestPromotedAddonVersion(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.promoted_group = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT
        )
        self.application_id = applications.FIREFOX.id
        self.required_fields = {
            'promoted_group': self.promoted_group,
            'version': self.addon.current_version,
            'application_id': self.application_id,
        }

    def test_required_fields(self):
        for field in self.required_fields.keys():
            missing_fields = {
                k: v for k, v in self.required_fields.items() if k != field
            }
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    PromotedAddonVersion.objects.create(**missing_fields)

        assert PromotedAddonVersion.objects.create(**self.required_fields) is not None

    def test_str_method(self):
        promoted_addon_version = PromotedAddonVersion.objects.create(
            **self.required_fields
        )

        assert str(promoted_addon_version) == (
            f'{self.promoted_group.name} - '
            f'{self.addon.current_version} - '
            f'{applications.FIREFOX.short}'
        )

    def test_unique_constraint(self):
        original = PromotedAddonVersion.objects.create(**self.required_fields)

        with (
            self.assertRaises(IntegrityError),
            transaction.atomic(),
        ):
            PromotedAddonVersion.objects.create(**self.required_fields)

        original.delete()
        assert PromotedAddonVersion.objects.create(**self.required_fields) is not None
