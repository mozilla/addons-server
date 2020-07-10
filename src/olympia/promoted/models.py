from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.constants.promoted import (
    NOT_PROMOTED, PROMOTED_GROUPS, PROMOTED_GROUPS_BY_ID)
from olympia.versions.models import Version


class PromotedAddon(ModelBase):
    GROUP_CHOICES = [(group.id, group.name) for group in PROMOTED_GROUPS]
    group_id = models.SmallIntegerField(
        choices=GROUP_CHOICES, default=NOT_PROMOTED.id)
    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE, null=False)

    @property
    def group(self):
        return PROMOTED_GROUPS_BY_ID.get(self.group_id, NOT_PROMOTED)

    @property
    def is_addon_currently_promoted(self):
        """Is the current_version of the addon approved for promotion within
        the *current* promoted group."""
        return bool(
            self.addon.current_version and
            self.group != NOT_PROMOTED.id and
            self.addon.current_version.promoted_approvals.filter(
                group_id=self.group_id).exists())


class PromotedApproval(ModelBase):
    GROUP_CHOICES = [
        (g.id, g.name) for g in PROMOTED_GROUPS if g != NOT_PROMOTED]
    group_id = models.SmallIntegerField(
        choices=GROUP_CHOICES, null=True)
    version = models.ForeignKey(
        Version, on_delete=models.CASCADE, null=False,
        related_name='promoted_approvals')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('group_id', 'version'),
                name='unique_promoted_version'),
        ]
