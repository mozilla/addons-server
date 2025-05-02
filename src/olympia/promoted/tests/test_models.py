from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants import applications
from olympia.constants.promoted import (
    DEACTIVATED_LEGACY_IDS,
    PROMOTED_GROUP_CHOICES,
    PROMOTED_GROUPS_BY_ID,
)
from olympia.promoted.models import (
    PromotedAddonPromotion,
    PromotedAddonVersion,
    PromotedGroup,
)


class TestPromotedGroupManager(TestCase):
    def setUp(self):
        self.addon: Addon = addon_factory()
        self.application_id = applications.FIREFOX.id

        self.promoted_group = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT
        )
        self.promotion = PromotedAddonPromotion.objects.create(
            addon=self.addon,
            promoted_group=self.promoted_group,
            application_id=self.application_id,
        )

    def test_unapproved_promoted_addon_promotion(self):
        # addon has a promotion, but no associated version (no approval)
        assert not PromotedGroup.objects.approved_for(self.addon)

    def test_approved_promoted_addon_promotion(self):
        # now approved, should appear in approved_for
        PromotedAddonVersion.objects.create(
            version=self.addon.current_version,
            promoted_group=self.promoted_group,
            application_id=self.application_id,
        )
        assert self.promoted_group in PromotedGroup.objects.approved_for(self.addon)

        # if the current version changes (the group was not
        # carried over) the approval is no longer valid
        self.addon._current_version = version_factory(addon=self.addon)
        assert not PromotedGroup.objects.approved_for(self.addon)

    def test_promoted_group_non_pre_reviewed(self):
        # alternatively, addon has a non-pre-reviewed promoted group
        strategic_group = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.STRATEGIC
        )
        self.promotion.promoted_group = strategic_group
        self.promotion.save()
        assert strategic_group in PromotedGroup.objects.approved_for(self.addon)

    def test_all_for(self):
        self.promotion.delete()
        assert PromotedAddonPromotion.objects.filter(addon=self.addon).count() == 0
        assert not PromotedGroup.objects.all_for(self.addon)

        PromotedAddonPromotion.objects.create(
            addon=self.addon,
            promoted_group=self.promoted_group,
            application_id=self.application_id,
        )

        # the addon is promoted in that group
        assert PromotedAddonPromotion.objects.filter(addon=self.addon).count() == 1
        assert self.promoted_group in PromotedGroup.objects.all_for(self.addon)

        # but not approved
        assert (
            PromotedAddonVersion.objects.filter(
                version=self.addon.current_version
            ).count()
            == 0
        )
        assert self.promoted_group not in PromotedGroup.objects.approved_for(self.addon)


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
        assert len(active_groups) == 7
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

    def test_multiple_applications_per_promoted_group_allowed(self):
        PromotedAddonPromotion.objects.create(**self.required_fields)
        assert (
            PromotedAddonPromotion.objects.create(
                **{**self.required_fields, 'application_id': applications.ANDROID.id}
            )
            is not None
        )

    def test_multiple_addons_per_application_group_allowed(self):
        PromotedAddonPromotion.objects.create(**self.required_fields)
        assert (
            PromotedAddonPromotion.objects.create(
                **{**self.required_fields, **{'addon': addon_factory()}}
            )
            is not None
        )

    def test_duplicate_raises(self):
        # Create the original instance to test constraints against
        original = PromotedAddonPromotion.objects.create(**self.required_fields)
        with (
            self.assertRaises(IntegrityError),
            transaction.atomic(),
        ):
            PromotedAddonPromotion.objects.create(**{**self.required_fields})
        # Delete the original instance to test the constraint
        # is lifted when it is deleted.
        original.delete()
        PromotedAddonPromotion.objects.create(**{**self.required_fields})


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
