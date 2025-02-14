from django.db import models
from django.db.models.signals import ModelSignal

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

    # Create the missing instances on the PromotedAddonPromotion model
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
