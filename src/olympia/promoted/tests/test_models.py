from unittest import mock

from django.db import IntegrityError, transaction

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants import applications
from olympia.constants.promoted import RECOMMENDED_API_NAME
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
    PromotedGroup,
)


class TestPromotedGroupManager(TestCase):
    def setUp(self):
        self.addon: Addon = addon_factory()
        self.application_id = applications.FIREFOX.id

        self.promoted_group = PromotedGroup.objects.get(api_name='spotlight')
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
        strategic_group = PromotedGroup.objects.get(api_name='strategic')
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
            promoted_group=PromotedGroup.objects.get(api_name='notable'),
            application_id=applications.FIREFOX.id,
        )
        self.promotion2 = PromotedAddon.objects.create(
            addon=self.addon,
            promoted_group=PromotedGroup.objects.get(api_name=RECOMMENDED_API_NAME),
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
    def test_str_method(self):
        # Ensure the __str__ method returns the name
        for pg in PromotedGroup.objects.all():
            self.assertEqual(str(pg), pg.name)

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def test_save_on_create_does_not_trigger_index_addons(self, index_addons_mock):
        PromotedGroup.objects.create(name='Test Group', api_name='test_create_group')
        assert index_addons_mock.call_count == 0

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def test_save_is_public_change_triggers_index_addons(self, index_addons_mock):
        group = PromotedGroup.objects.create(
            name='Test Group', api_name='test_group_public_change', is_public=True
        )
        addon = addon_factory(promoted_kwargs={'api_name': group.api_name})
        index_addons_mock.reset_mock()

        group.is_public = False
        group.save()

        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon.pk],)

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def _test_field_changes_triggers_when_public(self, field, index_addons_mock):
        group = PromotedGroup.objects.create(
            name='Test Group', api_name='test_group_bump', is_public=False
        )
        addon = addon_factory(promoted_kwargs={'api_name': group.api_name})
        index_addons_mock.reset_mock()

        setattr(group, field, 2.0)
        group.save()

        # should not trigger index_addons because the group is not public
        assert index_addons_mock.call_count == 0

        # Now make the group public and save again
        group.is_public = True
        group.save()
        index_addons_mock.reset_mock()  # ignore this index

        setattr(group, field, 3.0)
        group.save()
        assert index_addons_mock.call_count == 1
        assert index_addons_mock.call_args[0] == ([addon.pk],)

    def test_save_api_name_change_triggers_when_public(self):
        self._test_field_changes_triggers_when_public('api_name')

    def test_save_search_ranking_bump_change_triggers_when_public(self):
        self._test_field_changes_triggers_when_public('search_ranking_bump')

    @mock.patch('olympia.addons.tasks.index_addons.delay')
    def test_save_unrelated_change_does_not_trigger_index_addons(
        self, index_addons_mock
    ):
        group = PromotedGroup.objects.create(
            name='Test Group', api_name='test_group_unrelated', is_public=True
        )
        index_addons_mock.reset_mock()

        group.name = 'Test Group Renamed'
        group.save()

        assert index_addons_mock.call_count == 0


class TestPromotedAddon(TestCase):
    def setUp(self):
        self.addon: Addon = addon_factory()
        self.promoted_group = PromotedGroup.objects.get(api_name='spotlight')
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
            with self.assertRaises(IntegrityError), transaction.atomic():
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
                **{**self.required_fields, 'addon': addon_factory()}
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
            PromotedAddon.objects.create(**self.required_fields)
        # Delete the original instance to test the constraint
        # is lifted when it is deleted.
        original.delete()
        PromotedAddon.objects.create(**self.required_fields)


class TestPromotedApproval(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.promoted_group = PromotedGroup.objects.get(api_name='spotlight')
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
            with self.assertRaises(IntegrityError), transaction.atomic():
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
