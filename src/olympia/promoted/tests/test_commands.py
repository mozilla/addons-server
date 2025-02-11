from django.core.management import call_command
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

    def test_sync_promoted_no_op(self):
        self.sync_promoted_addons()

        self.assert_count(PromotedAddon, 0)
        self.assert_count(PromotedAddonPromotion, 0, addon=self.addon)

        self.assert_count(PromotedApproval, 0, version=self.addon.current_version)
        self.assert_count(PromotedAddonVersion, 0, version=self.addon.current_version)

    def test_sync_promoted_addons_with_promoted_addon(self):
        self.promoted_addon(
            group_id=PROMOTED_GROUP_CHOICES.LINE,
            application_id=amo.FIREFOX.id,
        )

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
        self.promoted_addon(
            # Spotlight has immediate approval so the approval is created
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            application_id=amo.FIREFOX.id,
        )

        self.sync_promoted_addons()

        self.assert_count(PromotedAddonPromotion, 1, addon=self.addon)
        self.assert_count(PromotedApproval, 1, version=self.addon.current_version)
        self.assert_count(PromotedAddonVersion, 1, version=self.addon.current_version)

    def test_sync_promoted_addons_approved_for_multiple_applications(self):
        self.promoted_addon(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            # 0 indicates approval for all applications
            application_id=0,
        )

        self.sync_promoted_addons()

        self.assert_count(
            PromotedAddonPromotion,
            1,
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        )
        self.assert_count(
            PromotedApproval,
            1,
            version=self.addon.current_version,
            application_id=amo.ANDROID.id,
        )
        # Expect 2 approvals and 2 promoted addon versions, 1 for each application
        self.assert_count(PromotedApproval, 2, version=self.addon.current_version)
        self.assert_count(PromotedAddonVersion, 2, version=self.addon.current_version)

    def test_sync_promoted_addon_change_group(self):
        promoted_addon = self.promoted_addon(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            application_id=amo.FIREFOX.id,
        )
        spotlight = self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT)

        self.sync_promoted_addons()

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=spotlight,
            application_id=amo.FIREFOX.id,
        )

        promoted_addon.update(group_id=PROMOTED_GROUP_CHOICES.LINE)
        self.sync_promoted_addons()

        promoted_addon_promotion.reload()
        group_id = promoted_addon_promotion.promoted_group.group_id
        assert group_id == PROMOTED_GROUP_CHOICES.LINE

    def test_promoted_addon_change_application(self):
        promoted_addon = self.promoted_addon(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            application_id=amo.FIREFOX.id,
        )
        self.sync_promoted_addons()

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.FIREFOX.id,
        )

        promoted_addon.update(application_id=amo.ANDROID.id)
        self.sync_promoted_addons()

        # The promotion has been deleted because the application has changed
        with self.assertRaises(PromotedAddonPromotion.DoesNotExist):
            promoted_addon_promotion.reload()

        promoted_addon_promotion = PromotedAddonPromotion.objects.get(
            addon=self.addon,
            promoted_group=self.promoted_group(PROMOTED_GROUP_CHOICES.SPOTLIGHT),
            application_id=amo.ANDROID.id,
        )

    def test_delete_promoted_addon(self):
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

    def test_delete_promoted_approval(self):
        self.promoted_addon(
            group_id=PROMOTED_GROUP_CHOICES.SPOTLIGHT,
            application_id=amo.FIREFOX.id,
        )
        self.sync_promoted_addons()

        self.assert_count(
            PromotedAddonVersion,
            1,
            version=self.addon.current_version,
            application_id=amo.FIREFOX.id,
        )

        PromotedApproval.objects.filter(
            version=self.addon.current_version,
            application_id=amo.FIREFOX.id,
        ).delete()

        self.assert_count(
            PromotedAddonVersion,
            0,
            version=self.addon.current_version,
            application_id=amo.FIREFOX.id,
        )
