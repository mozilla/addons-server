from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.constants.applications import APP_IDS, APPS_CHOICES
from olympia.constants.promoted import (
    NOT_PROMOTED, PROMOTED_GROUPS, PROMOTED_GROUPS_BY_ID)
from olympia.versions.models import Version


class PromotedAddon(ModelBase):
    GROUP_CHOICES = [(group.id, group.name) for group in PROMOTED_GROUPS]
    APPLICATION_CHOICES = ((None, 'All'),) + APPS_CHOICES
    group_id = models.SmallIntegerField(
        choices=GROUP_CHOICES, default=NOT_PROMOTED.id, verbose_name='Group',
        help_text='Can be set to Not Promoted to disable promotion without '
                  'deleting it.  Note: changing the group does *not* change '
                  'approvals of versions.')
    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE, null=False,
        help_text='Add-on id this item will point to (If you do not know the '
                  'id, paste the slug instead and it will be transformed '
                  'automatically for you. If you have access to the add-on '
                  'admin page, you can use the magnifying glass to see '
                  'all available add-ons.')
    application_id = models.SmallIntegerField(
        choices=APPLICATION_CHOICES, null=True, verbose_name='Application',
        blank=True)

    def __str__(self):
        return f'{self.get_group_id_display()} - {self.addon}'

    @property
    def group(self):
        return PROMOTED_GROUPS_BY_ID.get(self.group_id, NOT_PROMOTED)

    @property
    def application(self):
        return APP_IDS.get(self.application_id)

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
        choices=GROUP_CHOICES, null=True, verbose_name='Group')
    version = models.ForeignKey(
        Version, on_delete=models.CASCADE, null=False,
        related_name='promoted_approvals')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('group_id', 'version'),
                name='unique_promoted_version'),
        ]

    def __str__(self):
        return (
            f'{self.get_group_id_display()} - '
            f'{self.version.addon}: {self.version}')
