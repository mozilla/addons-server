from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from olympia import amo, core
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.constants import applications
from olympia.constants.promoted import (
    PROMOTED_GROUP_CHOICES,
)
from olympia.promoted.models import (
    PromotedAddon,
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
            PromotedAddonVersion.objects.filter(
                version=self.addon.current_version
            ).count()
            == 0
        )
        assert self.promoted_group not in PromotedGroup.objects.approved_for(self.addon)


class TestPromotedGroup(TestCase):
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
        promoted_addon_promotion = PromotedAddon.objects.create(
            **self.required_fields
        )
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
