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
from olympia.versions.utils import get_review_due_date


class TestPromotedAddon(TestCase):
    def setUp(self):
        self.task_user = user_factory(pk=settings.TASK_USER_ID)

    def promted_group(self, group_id):
        return PromotedGroup.objects.get(group_id=group_id)

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

        # Verify PromotedAddonPromotion instances were created for all applications
        assert (
            PromotedAddonPromotion.objects.filter(
                addon=promoted_addon.addon,
                promoted_group=self.promted_group(promoted_addon.group.id),
                application_id__in=[app.id for app in promoted_addon.all_applications],
            ).count()
            == 2
        )

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.all_applications == [applications.FIREFOX]

        # Verify the FIREFOX instance still exists
        assert PromotedAddonPromotion.objects.filter(
            addon=promoted_addon.addon,
            promoted_group=self.promted_group(promoted_addon.group.id),
            application_id=applications.FIREFOX.id,
        ).exists()

        # Verify the ANDROID instance was deleted
        assert not PromotedAddonPromotion.objects.filter(
            addon=promoted_addon.addon,
            promoted_group=self.promted_group(promoted_addon.group.id),
            application_id=applications.ANDROID.id,
        ).exists()

    def test_is_approved_applications(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.LINE
        )
        assert addon.promotedaddon
        assert PromotedAddonPromotion.objects.filter(
            addon=addon,
            promoted_group=self.promted_group(promoted_addon.group.id),
        ).exists()
        # Just having the PromotedAddon instance isn't enough
        assert addon.promotedaddon.approved_applications == []

        # There are no PromotedAddonVersions for the given promoted addon
        assert not PromotedAddonVersion.objects.filter(
            version=addon.current_version,
            promoted_group=self.promted_group(promoted_addon.group.id),
        ).exists()

        # the current version needs to be approved also
        promoted_addon.approve_for_version(addon.current_version)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        # Verify PromotedAddonVersions were created for the approved applications
        assert (
            PromotedAddonVersion.objects.filter(
                version=addon.current_version,
                promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.LINE),
            ).count()
            == 2
        )

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        # PromotedAddonPromotion instances' promoted_group should be updated
        assert (
            PromotedAddonPromotion.objects.filter(
                addon=promoted_addon.addon,
                promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            ).count()
            == 2
        )

        assert addon.promotedaddon.approved_applications == []
        # There should not yet be any PromotedAddonVersions for this addon
        assert not PromotedAddonVersion.objects.filter(
            version=addon.current_version,
            promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
        ).exists()

        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version,
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            application_id=applications.FIREFOX.id,
        )

        addon.reload()
        assert addon.promotedaddon.approved_applications == [applications.FIREFOX]
        # a PromotedAddonVersion should be created for the approved application
        assert PromotedAddonVersion.objects.filter(
            version=addon.current_version,
            promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=applications.FIREFOX.id,
        ).exists()

        # for promoted groups that don't require pre-review though, there isn't
        # a per version approval, so a current_version is sufficient and all
        # applications are seen as approved.
        promoted_addon.update(group_id=PROMOTED_GROUP_CHOICES.STRATEGIC)
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]
        # Verify PromotedAddonVersions were created for the approved applications
        assert list(
            PromotedAddonVersion.objects.filter(
                version=addon.current_version,
            )
            .values_list('application_id', flat=True)
            .distinct()
        ) == [
            applications.FIREFOX.id,
            applications.ANDROID.id,
        ]

    def test_auto_approves_addon_when_saved_for_immediate_approval(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        assert PromotedAddonPromotion.objects.filter(
            addon=promo.addon,
            promoted_group=self.promted_group(promo.group.id),
            application_id=amo.FIREFOX.id,
        ).exists()
        assert promo.group.id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert not PromotedAddonVersion.objects.exists()

        # first test with a group.immediate_approval == False
        promo.group_id = PROMOTED_GROUP_CHOICES.RECOMMENDED
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert not PromotedAddonVersion.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED

        # then with a group thats immediate_approval == True
        promo.group_id = PROMOTED_GROUP_CHOICES.SPOTLIGHT
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX]
        assert PromotedApproval.objects.count() == 1
        assert (
            PromotedAddonVersion.objects.filter(
                version=promo.addon.current_version,
                promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
                application_id=amo.FIREFOX.id,
            ).count()
            == 1
        )
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.SPOTLIGHT
        assert (
            PromotedAddonVersion.objects.filter(
                version=promo.addon.current_version,
                promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
                application_id=amo.FIREFOX.id,
            ).count()
            == 1
        )

        # test the edge case where the application was changed afterwards
        promo.application_id = 0
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX, amo.ANDROID]
        assert list(
            PromotedAddonPromotion.objects.filter(
                addon=promo.addon,
            )
            .values_list('application_id', flat=True)
            .distinct()
        ) == [
            amo.FIREFOX.id,
            amo.ANDROID.id,
        ]
        assert PromotedApproval.objects.count() == 2
        assert (
            PromotedAddonVersion.objects.filter(
                version=promo.addon.current_version,
                promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            ).count()
            == 2
        )

    def _test_addon_flagged_for_human_review(
        self,
        *,
        group_id,
        human_review_date=None,
        is_signed=True,
        expected_flag=False,
    ):
        """
        Test whether versions are flagged for human review
        when PromotedAddon is saved.

        Args:
            group_id (int): The promoted group id to test with
            human_review_date (datetime, optional): The human review date to set
            is_signed (bool): Whether versions should be signed
            expected_flag (bool): Whether versions should be flagged for review
        """
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        assert PromotedAddonPromotion.objects.filter(
            addon=promo.addon,
            promoted_group=self.promted_group(promo.group.id),
            application_id=amo.FIREFOX.id,
        ).exists()
        listed_ver = promo.addon.current_version
        unlisted_ver = version_factory(addon=promo.addon, channel=amo.CHANNEL_UNLISTED)

        # Set up version state based on arguments
        listed_ver.update(human_review_date=human_review_date)
        unlisted_ver.update(human_review_date=human_review_date)
        listed_ver.file.update(is_signed=is_signed)
        unlisted_ver.file.update(is_signed=is_signed)

        # Save with new group
        promo.group_id = group_id
        promo.save()
        promo.addon.reload()

        # Verify promotion state
        assert PromotedAddonPromotion.objects.filter(
            addon=promo.addon,
            promoted_group=self.promted_group(group_id),
        ).exists()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert not PromotedAddonVersion.objects.exists()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED

        # Verify version state
        listed_ver.refresh_from_db()
        unlisted_ver.refresh_from_db()

        if expected_flag:
            self.assertCloseToNow(listed_ver.due_date, now=get_review_due_date())
            self.assertCloseToNow(unlisted_ver.due_date, now=get_review_due_date())
            assert unlisted_ver.needshumanreview_set.filter(is_active=True).count() == 1
            assert unlisted_ver.needshumanreview_set.get().reason == (
                unlisted_ver.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
            )
            assert listed_ver.needshumanreview_set.filter(is_active=True).count() == 1
            assert (
                listed_ver.needshumanreview_set.get().reason
                == listed_ver.needshumanreview_set.model.REASONS.ADDED_TO_PROMOTED_GROUP
            )
        else:
            assert not listed_ver.due_date
            assert not unlisted_ver.due_date
            assert unlisted_ver.needshumanreview_set.count() == 0
            assert listed_ver.needshumanreview_set.count() == 0

    def test_addon_flagged_for_human_review_when_saved(self):
        # Test empty case with no group set
        self._test_addon_flagged_for_human_review(
            group_id=PROMOTED_GROUP_CHOICES.NOT_PROMOTED,
            expected_flag=False,
        )

        # Test with group.flag_for_human_review == False
        self._test_addon_flagged_for_human_review(
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            expected_flag=False,
        )

        # Test with group.flag_for_human_review == True but already human reviewed
        self._test_addon_flagged_for_human_review(
            group_id=PROMOTED_GROUP_CHOICES.NOTABLE,
            human_review_date=self.days_ago(1),
            expected_flag=False,
        )

        # Test with group.flag_for_human_review == True, no human review but unsigned
        self._test_addon_flagged_for_human_review(
            group_id=PROMOTED_GROUP_CHOICES.NOTABLE,
            is_signed=False,
            expected_flag=False,
        )

        # Test with group.flag_for_human_review == True, no human review and signed
        self._test_addon_flagged_for_human_review(
            group_id=PROMOTED_GROUP_CHOICES.NOTABLE,
            expected_flag=True,
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
        assert PromotedAddonPromotion.objects.filter(
            addon=promo.addon,
            promoted_group=self.promted_group(promo.group.id),
            application_id=amo.FIREFOX.id,
        ).exists()
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
        assert PromotedAddonPromotion.objects.filter(
            addon=promo.addon,
            promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        ).exists()
        # SPOTLIGHT doesnt have special signing states so won't be resigned
        # approve_for_addon is called automatically - SPOTLIGHT has immediate_approval
        promo.addon.reload()
        assert promo.addon.promoted_group().id == PROMOTED_GROUP_CHOICES.SPOTLIGHT
        assert promo.addon.current_version.version == '0.123a'
        assert PromotedAddonVersion.objects.filter(
            version=promo.addon.current_version,
            promoted_group=self.promted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        ).exists()


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
