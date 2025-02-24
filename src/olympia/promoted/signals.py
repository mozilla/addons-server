from django.db import models
from django.db.models.signals import ModelSignal

from olympia.constants.applications import APP_USAGE
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES

from .models import (
    PromotedAddon,
    PromotedAddonPromotion,
    PromotedAddonVersion,
    PromotedApproval,
    PromotedGroup,
)


def promoted_addon_to_promoted_addon_promotion(
    signal: ModelSignal, instance: PromotedAddon
):
    promoted_group = PromotedGroup.objects.get(group_id=instance.group_id)

    # Create the missing instances on the PromotedAddonPromotion model.
    # If its update to NOT_PROMOTED, then delete the existing instead.
    if promoted_group.group_id != PROMOTED_GROUP_CHOICES.NOT_PROMOTED:
        PromotedAddonPromotion.objects.update_or_create(
            addon=instance.addon,
            application_id=instance.application_id,
            defaults={
                'promoted_group': promoted_group,
            },
        )
    elif instance.pk:
        PromotedAddonPromotion.objects.filter(addon=instance.addon).delete()

    # If the addon has previously been approved, OR
    # the promoted group is not badged
    # (see test_unbadged_non_prereview_promoted_can_be_disabled_and_deleted):
    # (i.e has existing approvals) for the current group:
    # If promotedaddon's application_id is not None,
    # delete the PromotedAddonVersions that are not the current application_id
    # and make sure the current application_id exists.
    # Otherwise, it should be available for all applications.
    # This should mirror the behaviour of PromotedAddon's all_applications()
    # when used by approved_applications.

    existing_approval = PromotedApproval.objects.filter(
        version=instance.addon.current_version, group_id=promoted_group.group_id
    )

    if existing_approval.exists() or not promoted_group.badged:
        if instance.application_id:
            PromotedAddonVersion.objects.filter(
                version=instance.addon.current_version
            ).exclude(application_id=instance.application_id).delete()
            PromotedAddonVersion.objects.update_or_create(
                version=instance.addon.current_version,
                promoted_group=promoted_group,
                application_id=instance.application_id,
            )
        elif instance.addon.current_version:
            for app in APP_USAGE:
                PromotedAddonVersion.objects.update_or_create(
                    version=instance.addon.current_version,
                    promoted_group=promoted_group,
                    application_id=app.id,
                )


def promoted_approval_to_promoted_addon_version(
    signal: ModelSignal,
    instance: PromotedApproval,
):
    if signal == models.signals.post_save:
        PromotedAddonVersion.objects.update_or_create(
            version=instance.version,
            promoted_group=PromotedGroup.objects.get(group_id=instance.group_id),
            application_id=instance.application_id,
        )
    elif signal == models.signals.post_delete:
        PromotedAddonVersion.objects.filter(
            version=instance.version,
            promoted_group=PromotedGroup.objects.get(group_id=instance.group_id),
            application_id=instance.application_id,
        ).delete()
