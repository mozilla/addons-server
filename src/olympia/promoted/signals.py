from django.db import models, transaction
from django.db.models.signals import ModelSignal

from olympia.amo.decorators import use_primary_db
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES

from .models import (
    PromotedAddon,
    PromotedAddonPromotion,
    PromotedAddonVersion,
    PromotedApproval,
    PromotedGroup,
)


@use_primary_db
def promoted_addon_to_promoted_addon_promotion(
    signal: ModelSignal, instance: PromotedAddon
):
    promoted_group = PromotedGroup.objects.get(group_id=instance.group_id)

    # Create the missing instances on the PromotedAddonPromotion model.
    # If its update to NOT_PROMOTED, then delete the existing instead.
    if promoted_group.group_id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED:
        if instance.pk:
            PromotedAddonPromotion.objects.filter(addon=instance.addon).delete()
        return

    # Get the current set of app ids related to both models for the addon/group
    # If we are deleting,  then the set should be empty
    promoted_addon_app_ids = set(
        [app.id for app in instance.all_applications]
        if signal == models.signals.post_save
        else []
    )

    # Get the current set of app ids related to both models for the addon/group
    promoted_addon_promotion_app_ids = set(
        PromotedAddonPromotion.objects.filter(
            addon=instance.addon,
            promoted_group=promoted_group,
        ).values_list('application_id', flat=True)
    )

    # Diff the app ids to determine which ones to add and which ones to remove
    promotions_to_add = promoted_addon_app_ids - promoted_addon_promotion_app_ids
    promotions_to_remove = promoted_addon_promotion_app_ids - promoted_addon_app_ids

    # Create the missing instances on the PromotedAddonPromotion model.
    for app_id in promotions_to_add:
        PromotedAddonPromotion.objects.update_or_create(
            addon=instance.addon,
            application_id=app_id,
            defaults={
                'promoted_group': promoted_group,
            },
        )

    # Delete extra instances on the PromotedAddonPromotion model
    # that are no longer on the PromotedAddon instance
    for app_id in promotions_to_remove:
        PromotedAddonPromotion.objects.filter(
            addon=instance.addon,
            application_id=app_id,
        ).delete()


@use_primary_db
def promoted_approval_to_promoted_addon_version(
    signal: ModelSignal,
    instance: PromotedApproval,
):
    # Get all valid approvals for this version
    valid_approvals = []
    for approval in PromotedApproval.objects.filter(version=instance.version):
        # Skip invalid approvals
        if (
            approval.group_id is None
            or approval.group_id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
            or approval.application_id is None
        ):
            continue

        try:
            promoted_group = PromotedGroup.objects.get(group_id=approval.group_id)
            valid_approvals.append((promoted_group, approval.application_id))
        except PromotedGroup.DoesNotExist:
            continue

    with transaction.atomic():
        # First, delete all PromotedAddonVersions for this version
        PromotedAddonVersion.objects.filter(version=instance.version).delete()
        # Then re-create versions based on valid approvals
        PromotedAddonVersion.objects.bulk_create(
            [
                PromotedAddonVersion(
                    version=instance.version,
                    promoted_group=promoted_group,
                    application_id=application_id,
                )
                for promoted_group, application_id in valid_approvals
            ]
        )
