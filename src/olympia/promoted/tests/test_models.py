from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants import applications
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
    PromotedGroup,
)


class TestPromotedGroupManager(TestCase):
    def setUp(self):
        self.addon: Addon = addon_factory()
        self.application_id = applications.FIREFOX.id

        self.promoted_group = PromotedGroup.objects.get(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT
        )
        self.promotion = PromotedAddon.objects.create(
            addon=self.addon,
            promoted_group=self.promoted_group,
            application_id=self.application_id,
        )

    def test_unapproved_promoted_addon_promotion(self):
        # addon has a promotion, but no associated version (no approval)
        assert not PromotedGroup.objects.approved_for(self.addon)

    def test_approved_promoted_addon_promotion(self):
        # now approved, should appear in approved_for
        PromotedApproval.objects.create(
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
        assert PromotedAddon.objects.filter(addon=self.addon).count() == 0
        assert not PromotedGroup.objects.all_for(self.addon)

        PromotedAddon.objects.create(
            addon=self.addon,
            promoted_group=self.promoted_group,
            application_id=self.application_id,
        )

        # the addon is promoted in that group
        assert PromotedAddon.objects.filter(addon=self.addon).count() == 1
        assert self.promoted_group in PromotedGroup.objects.all_for(self.addon)

        # but not approved
        assert (
            PromotedApproval.objects.filter(version=self.addon.current_version).count()
            == 0
        )
        assert self.promoted_group not in PromotedGroup.objects.approved_for(self.addon)


class TestPromotedGroupQuerySet(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.promotion1 = PromotedAddon.objects.create(
            addon=self.addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.NOTABLE
            ),
            application_id=applications.FIREFOX.id,
        )
        self.promotion2 = PromotedAddon.objects.create(
            addon=self.addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=applications.FIREFOX.id,
        )

    def test_getattr(self):
        promoted_groups = self.addon.promoted_groups(currently_approved=False)
        with self.assertNumQueries(1):
            assert promoted_groups.listed_pre_review == [True, True]
        with self.assertNumQueries(0):
            assert set(promoted_groups.unlisted_pre_review) == {False, True}
        with self.assertNumQueries(0):
            assert set(promoted_groups.badged) == {False, True}


class TestPromotedGroup(TestCase):
    def test_deactived_group_ids_raise(self):
        for group in PROMOTED_GROUP_CHOICES.entries:
            if group in PROMOTED_GROUP_CHOICES.ACTIVE.entries:
                continue
            with self.assertRaises(ValidationError):
                PromotedGroup.objects.create(
                    group_id=group.value,
                    name='Test',
                    api_name='test',
                )

    def test_str_method(self):
        # Ensure the __str__ method returns the name
        for pg in PromotedGroup.objects.all():
            self.assertEqual(str(pg), pg.name)


class TestPromotedAddon(TestCase):
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
                    PromotedAddon.objects.create(**missing_fields)

        assert PromotedAddon.objects.create(**self.required_fields) is not None

    def test_str_method(self):
        promoted_addon_promotion = PromotedAddon.objects.create(**self.required_fields)
        assert str(promoted_addon_promotion) == (
            f'{self.promoted_group.name} - {self.addon} - {applications.FIREFOX.short}'
        )

    def _test_unique_constraint(self, fields, should_raise=False):
        # Create the original instance to test constraints against
        original = PromotedAddon.objects.create(**self.required_fields)
        # merge the fields with the required fields
        merged = {**self.required_fields, **fields}
        if should_raise:
            # Should raise while the original instance exists
            with (
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                PromotedAddon.objects.create(**merged)
            # Delete the original instance to test the constraint
            # is lifted when it is deleted.
            original.delete()

        assert PromotedAddon.objects.create(**merged) is not None

    def test_multiple_applications_per_promoted_group_allowed(self):
        PromotedAddon.objects.create(**self.required_fields)
        assert (
            PromotedAddon.objects.create(
                **{**self.required_fields, 'application_id': applications.ANDROID.id}
            )
            is not None
        )

    def test_multiple_addons_per_application_group_allowed(self):
        PromotedAddon.objects.create(**self.required_fields)
        assert (
            PromotedAddon.objects.create(
                **{**self.required_fields, **{'addon': addon_factory()}}
            )
            is not None
        )

    def test_duplicate_raises(self):
        # Create the original instance to test constraints against
        original = PromotedAddon.objects.create(**self.required_fields)
        with (
            self.assertRaises(IntegrityError),
            transaction.atomic(),
        ):
            PromotedAddon.objects.create(**{**self.required_fields})
        # Delete the original instance to test the constraint
        # is lifted when it is deleted.
        original.delete()
        PromotedAddon.objects.create(**{**self.required_fields})


class TestPromotedApproval(TestCase):
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
                    PromotedApproval.objects.create(**missing_fields)

        assert PromotedApproval.objects.create(**self.required_fields) is not None

    def test_str_method(self):
        promoted_addon_version = PromotedApproval.objects.create(**self.required_fields)

        assert str(promoted_addon_version) == (
            f'{self.promoted_group.name} - '
            f'{self.addon.current_version} - '
            f'{applications.FIREFOX.short}'
        )

    def test_unique_constraint(self):
        original = PromotedApproval.objects.create(**self.required_fields)

        with (
            self.assertRaises(IntegrityError),
            transaction.atomic(),
        ):
            PromotedApproval.objects.create(**self.required_fields)

        original.delete()
        assert PromotedApproval.objects.create(**self.required_fields) is not None
