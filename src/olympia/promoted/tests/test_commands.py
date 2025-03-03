import contextlib

from django.core.management import call_command
from django.db.models.signals import post_save
from django.test import TestCase

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import (
    PromotedAddon,
    PromotedAddonPromotion,
    PromotedAddonVersion,
    PromotedApproval,
    PromotedGroup,
    promoted_addon_to_promoted_addon_promotion,
    promoted_approval_to_promoted_addon_version,
)


class TestSyncPromoted(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def assert_count(self, model, count, **kwargs):
        assert model.objects.filter(**kwargs).count() == count

    def sync_promoted_addons(self):
        call_command('sync_promoted_addons')

    def promoted_addon(self, addon=None, **kwargs):
        return PromotedAddon.objects.create(addon=addon or self.addon, **kwargs)

    def promoted_group(self, group_id):
        return PromotedGroup.objects.get(group_id=group_id)

    @contextlib.contextmanager
    def with_disabled_signal(self, signal, reciever, *args, **kwargs):
        signal.disconnect(reciever, *args, **kwargs)
        try:
            yield
        finally:
            signal.connect(reciever, *args, **kwargs)

    def disable_post_save_promoted_addon(self):
        return self.with_disabled_signal(
            post_save,
            promoted_addon_to_promoted_addon_promotion,
            sender=PromotedAddon,
            dispatch_uid='addons.sync_promoted.promoted_addon',
        )

    def disable_post_save_promoted_approval(self):
        return self.with_disabled_signal(
            post_save,
            promoted_approval_to_promoted_addon_version,
            sender=PromotedApproval,
            dispatch_uid='addons.sync_promoted.promoted_approval',
        )

    def test_sync_promoted_no_op(self):
        self.sync_promoted_addons()

        self.assert_count(PromotedAddon, 0)
        self.assert_count(PromotedAddonPromotion, 0, addon=self.addon)

        self.assert_count(PromotedApproval, 0, version=self.addon.current_version)
        self.assert_count(PromotedAddonVersion, 0, version=self.addon.current_version)

    def test_sync_promoted_addons_with_promoted_addon(self):
        with self.disable_post_save_promoted_addon():
            self.promoted_addon(
                group_id=PROMOTED_GROUP_CHOICES.LINE,
                application_id=amo.FIREFOX.id,
            )
            self.assert_count(PromotedAddonPromotion, 0)

        self.sync_promoted_addons()

        self.assert_count(
            PromotedAddonPromotion,
            1,
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.LINE),
            application_id=amo.FIREFOX.id,
        )
        self.assert_count(PromotedApproval, 0, version=self.addon.current_version)
        self.assert_count(PromotedAddonVersion, 0, version=self.addon.current_version)

    def test_sync_promoted_addons_with_promoted_approval(self):
        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            self.promoted_addon(
                # Spotlight has immediate approval so the approval is created
                group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
                application_id=amo.FIREFOX.id,
            )
            self.assert_count(PromotedAddonPromotion, 0)
            self.assert_count(PromotedAddonVersion, 0)
            self.assert_count(PromotedApproval, 1, version=self.addon.current_version)

        self.sync_promoted_addons()

        self.assert_count(PromotedAddonPromotion, 1, addon=self.addon)
        self.assert_count(PromotedAddonVersion, 1, version=self.addon.current_version)

    def test_sync_promoted_addons_approved_for_multiple_applications(self):
        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            self.promoted_addon(
                group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
                # 0 indicates approval for all applications
                application_id=0,
            )
            self.assert_count(PromotedAddonPromotion, 0)
            self.assert_count(PromotedAddonVersion, 0)
            self.assert_count(PromotedApproval, 2, version=self.addon.current_version)

        self.sync_promoted_addons()

        self.assert_count(
            PromotedAddonPromotion,
            1,
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        )
        # Expect 2 approvals and 2 promoted addon versions, 1 for each application
        self.assert_count(PromotedAddonVersion, 2, version=self.addon.current_version)

    def test_sync_promoted_addon_change_group(self):
        spotlight = self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        line = self.promoted_group(PROMOTED_GROUP_CHOICES.LINE)

        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            promoted_addon = self.promoted_addon(
                group_id=spotlight.group_id,
                application_id=amo.FIREFOX.id,
            )

            self.assert_count(PromotedAddonPromotion, 0)
            self.assert_count(PromotedAddonVersion, 0)
            self.assert_count(
                PromotedApproval,
                1,
                version=self.addon.current_version,
                group_id=spotlight.group_id,
                application_id=amo.FIREFOX.id,
            )

        self.sync_promoted_addons()

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=spotlight,
            application_id=amo.FIREFOX.id,
        )
        promoted_addon_version = PromotedAddonVersion.objects.get(
            version=self.addon.current_version,
            promoted_group=spotlight,
            application_id=amo.FIREFOX.id,
        )
        promoted_approval = PromotedApproval.objects.get(
            version=self.addon.current_version,
            group_id=spotlight.group_id,
            application_id=amo.FIREFOX.id,
        )

        # Update the promoted addon group without triggering the post_save signals
        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            promoted_addon.update(group_id=line.group_id)

        self.sync_promoted_addons()

        # Expect the promoted addon promotion group to change
        self.assertEqual(promoted_addon_promotion.reload().promoted_group, line)
        # Expect the promoted addon version and approval not to have changed
        # This is because the approval was created for the original promoted group
        # and would require a new approval
        self.assertEqual(promoted_approval.reload().group_id, spotlight.group_id)
        self.assertEqual(promoted_addon_version.reload().promoted_group, spotlight)

    def test_promoted_addon_change_application(self):
        spotlight = self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            promoted_addon = self.promoted_addon(
                group_id=spotlight.group_id,
                application_id=amo.FIREFOX.id,
            )
            self.assert_count(PromotedAddonPromotion, 0)
            self.assert_count(PromotedAddonVersion, 0)
            promoted_approval = PromotedApproval.objects.get(
                version=self.addon.current_version,
                group_id=spotlight.group_id,
                application_id=amo.FIREFOX.id,
            )

        self.sync_promoted_addons()

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=spotlight,
            application_id=amo.FIREFOX.id,
        )
        promoted_addon_version = PromotedAddonVersion.objects.get(
            version=self.addon.current_version,
            promoted_group=spotlight,
            application_id=amo.FIREFOX.id,
        )

        # Update the promoted addon application without triggering the post_save signals
        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            promoted_addon.update(application_id=amo.ANDROID.id)

        # Nothing has been changed yet because the signal has not been triggered
        # and approvals do not sync to promoted addon application updates
        for instance in (
            promoted_addon_promotion,
            promoted_addon_version,
            promoted_approval,
        ):
            assert instance.reload().application_id == amo.FIREFOX.id

        self.sync_promoted_addons()

        # The promotion has been deleted because the application has changed
        with self.assertRaises(PromotedAddonPromotion.DoesNotExist):
            promoted_addon_promotion.reload()

        # The approval and version have not been deleted or updated because the
        # new application would require approval, but the old application is still
        # approved. This could be a bug but the goal is for the models to sync correctly
        # even if the underlying logic does not make sense.
        self.assertEqual(promoted_approval.reload().group_id, spotlight.group_id)
        self.assertEqual(promoted_addon_version.reload().promoted_group, spotlight)

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.ANDROID.id,
        )
        # There are no approvals for the new application yet
        self.assert_count(
            PromotedApproval,
            0,
            version=self.addon.current_version,
            application_id=amo.ANDROID.id,
        )
        self.assert_count(
            PromotedAddonVersion,
            0,
            version=self.addon.current_version,
            application_id=amo.ANDROID.id,
        )

    def test_delete_promoted_addon(self):
        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            promoted_addon = self.promoted_addon(
                group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
                application_id=amo.FIREFOX.id,
            )

            # Create another promoted addon for the same group/application
            other_addon = addon_factory()
            self.promoted_addon(
                addon=other_addon,
                group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
                application_id=amo.FIREFOX.id,
            )
            self.assert_count(PromotedAddon, 2)
            self.assert_count(PromotedAddonPromotion, 0)
            self.assert_count(PromotedApproval, 2)
            self.assert_count(PromotedAddonVersion, 0)

        self.sync_promoted_addons()

        self.assert_count(
            PromotedAddonPromotion,
            2,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        )

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        )

        promoted_addon.delete()

        with self.assertRaises(PromotedAddonPromotion.DoesNotExist):
            promoted_addon_promotion.reload()

        self.assert_count(
            PromotedAddonPromotion,
            1,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        )

    def test_delete_promoted_addon_alread_deleted(self):
        spotlight = self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        promoted_addon = self.promoted_addon(
            group_id=spotlight.group_id,
            application_id=amo.FIREFOX.id,
        )
        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=spotlight,
            application_id=amo.FIREFOX.id,
        )
        # Delete the promoted addon promotion first
        promoted_addon_promotion.delete()
        # Deleting the promoted addon should trigger the post_delete signal
        # there should be no error if the promoted addon promotion is already deleted
        promoted_addon.delete()

    def test_delete_promoted_approval(self):
        spotlight = self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT)

        with (
            self.disable_post_save_promoted_addon(),
            self.disable_post_save_promoted_approval(),
        ):
            self.promoted_addon(
                group_id=spotlight.group_id,
                application_id=amo.FIREFOX.id,
            )
            self.assert_count(PromotedAddonPromotion, 0)
            self.assert_count(PromotedAddonVersion, 0)
            promoted_approval = PromotedApproval.objects.get(
                version=self.addon.current_version,
                application_id=amo.FIREFOX.id,
            )

        self.sync_promoted_addons()

        promoted_addon_version = PromotedAddonVersion.objects.get(
            version=self.addon.current_version,
            application_id=amo.FIREFOX.id,
        )

        promoted_approval.delete()

        with self.assertRaises(PromotedAddonVersion.DoesNotExist):
            promoted_addon_version.reload()

    def test_delete_promoted_addon_version(self):
        spotlight = self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT)
        self.promoted_addon(
            group_id=spotlight.group_id,
            application_id=amo.FIREFOX.id,
        )
        promoted_addon_version = PromotedAddonVersion.objects.get(
            version=self.addon.current_version,
            application_id=amo.FIREFOX.id,
        )
        promoted_addon_version.delete()

        # Deleting the promoted approval will trigger the post_delete signal
        # and there should be no error if the promoted addon version is already deleted
        PromotedApproval.objects.filter(
            version=self.addon.current_version,
            application_id=amo.FIREFOX.id,
        ).delete()
