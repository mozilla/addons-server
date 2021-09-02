from django.db import models
from django.dispatch import receiver

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.constants.applications import APP_IDS, APPS_CHOICES, APP_USAGE
from olympia.constants.promoted import (
    NOT_PROMOTED,
    PRE_REVIEW_GROUPS,
    PROMOTED_GROUPS,
    PROMOTED_GROUPS_BY_ID,
)
from olympia.versions.models import Version


class PromotedAddon(ModelBase):
    GROUP_CHOICES = [(group.id, group.name) for group in PROMOTED_GROUPS]
    APPLICATION_CHOICES = ((None, 'All Applications'),) + APPS_CHOICES
    group_id = models.SmallIntegerField(
        choices=GROUP_CHOICES,
        default=NOT_PROMOTED.id,
        verbose_name='Group',
        help_text='Can be set to Not Promoted to disable promotion without '
        'deleting it.  Note: changing the group does *not* change '
        'approvals of versions.',
    )
    addon = models.OneToOneField(
        Addon,
        on_delete=models.CASCADE,
        null=False,
        help_text='Add-on id this item will point to (If you do not know the '
        'id, paste the slug instead and it will be transformed '
        'automatically for you. If you have access to the add-on '
        'admin page, you can use the magnifying glass to see '
        'all available add-ons.',
    )
    application_id = models.SmallIntegerField(
        choices=APPLICATION_CHOICES, null=True, verbose_name='Application', blank=True
    )

    def __init__(self, *args, **kwargs):
        if 'approved_application_ids' in kwargs:
            apps = kwargs.pop('approved_application_ids')
            kwargs['application_id'] = self._get_application_id_from_applications(apps)
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f'{self.get_group_id_display()} - {self.addon}'

    @property
    def group(self):
        return PROMOTED_GROUPS_BY_ID.get(self.group_id, NOT_PROMOTED)

    @property
    def all_applications(self):
        application = APP_IDS.get(self.application_id)
        return [application] if application else [app for app in APP_USAGE]

    @property
    def approved_applications(self):
        """The applications that the current promoted group is approved for."""
        group = self.group
        all_apps = self.all_applications
        if group == NOT_PROMOTED or not self.addon.current_version:
            return []
        if not group.pre_review:
            return all_apps
        return [
            app
            for group_, app in self.addon.current_version.approved_for_groups
            if group_ == group and app in all_apps
        ]

    @property
    def has_approvals(self):
        return bool(self.approved_applications)

    def _get_application_id_from_applications(self, apps):
        """Return the application_id the instance would have for the specified
        app ids."""
        # i.e. app(id) if single app; 0 for all apps if many; or none otherwise
        return apps[0] if len(apps) == 1 else 0 if apps else None

    def approve_for_version(self, version):
        """Create PromotedApproval for current applications in the current
        promoted group."""
        for app in self.all_applications:
            PromotedApproval.objects.update_or_create(
                version=version, group_id=self.group_id, application_id=app.id
            )
        try:
            del version.approved_for_groups
        except AttributeError:
            pass

    def approve_for_addon(self):
        """This sets up the addon as approved for the current promoted group.

        The current version will be signed for approval, and if there's special
        signing needed for that group the version will be resigned."""
        from olympia.lib.crypto.tasks import sign_addons

        if not self.addon.current_version:
            return
        self.approve_for_version(self.addon.current_version)
        if self.group.autograph_signing_states:
            sign_addons([self.addon.id], send_emails=False)

    def get_resigned_version_number(self):
        """Returns what the new version number would be if approved_for_addon
        was called.  If no version would be signed return None."""
        from olympia.lib.crypto.tasks import get_new_version_number

        version = self.addon.current_version
        if version and not version.is_all_unreviewed:
            return get_new_version_number(version.version)
        else:
            return None

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if (
            self.group.immediate_approval
            and self.approved_applications != self.all_applications
        ):
            self.approve_for_addon()


class PromotedTheme(PromotedAddon):
    """A wrapper around PromotedAddon to use for themes in the featured
    collection."""

    class Meta(PromotedAddon.Meta):
        proxy = True

    @property
    def approved_applications(self):
        if self.group == NOT_PROMOTED or not self.addon.current_version:
            return []
        return self.all_applications

    def save(self, *args, **kwargs):
        raise NotImplementedError


class PromotedApproval(ModelBase):
    GROUP_CHOICES = [(g.id, g.name) for g in PRE_REVIEW_GROUPS]
    group_id = models.SmallIntegerField(
        choices=GROUP_CHOICES, null=True, verbose_name='Group'
    )
    version = models.ForeignKey(
        Version, on_delete=models.CASCADE, null=False, related_name='promoted_approvals'
    )
    application_id = models.SmallIntegerField(
        choices=APPS_CHOICES, null=True, verbose_name='Application', default=None
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('group_id', 'version', 'application_id'),
                name='unique_promoted_version',
            ),
        ]

    def __str__(self):
        return (
            f'{self.get_group_id_display()} - ' f'{self.version.addon}: {self.version}'
        )

    @property
    def application(self):
        return APP_IDS.get(self.application_id)


@receiver(
    models.signals.post_save, sender=PromotedAddon, dispatch_uid='addons.search.index'
)
def update_es_for_promoted(sender, instance, **kw):
    from olympia.addons.models import update_search_index
    from olympia.amo.tasks import trigger_sync_objects_to_basket

    # Update ES because Addon.promoted depends on it.
    update_search_index(sender=sender, instance=instance.addon, **kw)

    # Sync the related add-on to basket when promoted groups is changed
    trigger_sync_objects_to_basket('addon', [instance.addon.pk], 'promoted change')


@receiver(
    models.signals.post_save,
    sender=PromotedApproval,
    dispatch_uid='addons.search.index',
)
def update_es_for_promoted_approval(sender, instance, **kw):
    update_es_for_promoted(sender=sender, instance=instance.version, **kw)
