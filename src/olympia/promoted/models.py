from django.conf import settings
from django.db import models
from django.dispatch import receiver
from urllib.parse import urljoin

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.constants.applications import APP_IDS, APPS_CHOICES, APP_USAGE
from olympia.constants.promoted import (
    NOT_PROMOTED, PRE_REVIEW_GROUPS, PROMOTED_GROUPS, PROMOTED_GROUPS_BY_ID)
from olympia.versions.models import Version


class PromotedAddon(ModelBase):
    GROUP_CHOICES = [(group.id, group.name) for group in PROMOTED_GROUPS]
    APPLICATION_CHOICES = ((None, 'All Applications'),) + APPS_CHOICES
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
            if group_ == group and app in all_apps]

    def approve_for_version(self, version):
        """Create PromotedApproval for current applications in the current
        promoted group."""
        for app in self.all_applications:
            PromotedApproval.objects.update_or_create(
                version=version,
                group_id=self.group_id,
                application_id=app.id)


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
        choices=GROUP_CHOICES, null=True, verbose_name='Group')
    version = models.ForeignKey(
        Version, on_delete=models.CASCADE, null=False,
        related_name='promoted_approvals')
    application_id = models.SmallIntegerField(
        choices=APPS_CHOICES, null=True, verbose_name='Application',
        default=None)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('group_id', 'version', 'application_id'),
                name='unique_promoted_version'),
        ]

    def __str__(self):
        return (
            f'{self.get_group_id_display()} - '
            f'{self.version.addon}: {self.version}')

    @property
    def application(self):
        return APP_IDS.get(self.application_id)


@receiver(models.signals.post_save, sender=PromotedAddon,
          dispatch_uid='addons.search.index')
def update_es_for_promoted(sender, instance, **kw):
    from olympia.addons.models import update_search_index
    from olympia.amo.tasks import sync_object_to_basket

    # Update ES because Addon.promoted depends on it.
    update_search_index(sender=sender, instance=instance.addon, **kw)

    # Sync the related add-on to basket when promoted groups is changed
    sync_object_to_basket.delay('addon', instance.addon.pk)


@receiver(models.signals.post_save, sender=PromotedApproval,
          dispatch_uid='addons.search.index')
def update_es_for_promoted_approval(sender, instance, **kw):
    update_es_for_promoted(
        sender=sender, instance=instance.version, **kw)


class PromotedSubscription(ModelBase):
    promoted_addon = models.OneToOneField(
        PromotedAddon,
        on_delete=models.CASCADE,
        null=False,
    )
    link_visited_at = models.DateTimeField(
        null=True,
        help_text=(
            "This date is set when the developer has visited the onboarding "
            "page."
        ),
    )
    stripe_session_id = models.CharField(
        default=None, null=True, max_length=100
    )
    payment_cancelled_at = models.DateTimeField(
        null=True,
        help_text=(
            "This date is set when the developer has cancelled the payment "
            "process."
        ),
    )
    paid_at = models.DateTimeField(
        null=True,
        help_text=(
            "This date is set when the developer successfully completed the"
            " payment process."
        ),
    )

    def __str__(self):
        return f'Subscription for {self.promoted_addon}'

    def get_onboarding_url(self):
        if not self.id:
            return None
        return urljoin(
            settings.EXTERNAL_SITE_URL,
            # TODO: replace with `reverse()` once we have a route/view.
            f'/{self.promoted_addon.addon.slug}/onboarding'
        )
