from django.core.exceptions import ValidationError
from django.db import models
from django.dispatch import receiver

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.constants.applications import APP_IDS, APP_USAGE, APPS_CHOICES
from olympia.constants.promoted import (
    DEACTIVATED_LEGACY_IDS,
    PROMOTED_GROUP_CHOICES,
    PROMOTED_GROUPS_BY_ID,
)
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.models import Version


class PromotedGroup(models.Model):
    """A promotion group defining the promotion rules for add-ons.
    NOTE: This model replaces the legacy PromotedClass and its constants
    """

    group_id = models.SmallIntegerField(
        help_text='The legacy ID from back when promoted groups were static classes',
        choices=PROMOTED_GROUP_CHOICES,
    )
    name = models.CharField(
        max_length=255, help_text='Human-readable name for the promotion group.'
    )
    api_name = models.CharField(
        max_length=100, help_text='Programmatic API name for the promotion group.'
    )
    search_ranking_bump = models.FloatField(
        help_text=(
            'Boost value used to influence search ranking for add-ons in this group.'
        ),
        default=0.0,
    )
    listed_pre_review = models.BooleanField(
        default=False, help_text='Indicates if listed versions require pre-review.'
    )
    unlisted_pre_review = models.BooleanField(
        default=False, help_text='Indicates if unlisted versions require pre-review.'
    )
    admin_review = models.BooleanField(
        default=False,
        help_text='Specifies whether the promotion requires administrative review.',
    )
    badged = models.BooleanField(
        default=False,
        help_text='Specifies if the add-on receives a badge upon promotion.',
    )
    autograph_signing_states = models.JSONField(
        default=dict,
        help_text='Mapping of application shorthand to autograph signing states.',
    )
    can_primary_hero = models.BooleanField(
        default=False,
        help_text='Determines if the add-on can be featured in a primary hero shelf.',
    )
    immediate_approval = models.BooleanField(
        default=False, help_text='If true, add-ons are auto-approved upon saving.'
    )
    flag_for_human_review = models.BooleanField(
        default=False, help_text='If true, add-ons are flagged for manual human review.'
    )
    can_be_compatible_with_all_fenix_versions = models.BooleanField(
        default=False,
        help_text='Determines compatibility with all Fenix (Android) versions.',
    )
    high_profile = models.BooleanField(
        default=False,
        help_text='Indicates if the add-on is high-profile for review purposes.',
    )
    high_profile_rating = models.BooleanField(
        default=False,
        help_text='Indicates if developer replies are treated as high-profile.',
    )
    active = models.BooleanField(
        default=False,
        help_text=(
            'Marks whether this promotion group is active '
            '(inactive groups are considered obsolete).'
        ),
    )

    def __bool__(self):
        """
        When we use a PromotedGroup in a boolean context, we should treat NOT_PROMOTED
        as falsey. This is how the rest of the code base expects it. Eventually,
        we should consider deprectaing the NOT_PROMOTED group which could yield
        the same result via a database query simply not returning a promoted group.
        """
        return bool(self.group_id != PROMOTED_GROUP_CHOICES.NOT_PROMOTED)

    def save(self, *args, **kwargs):
        # Obsolete, never used in production, only there to prevent us from re-using
        # the ids. Both these classes used to have specific properties set that were
        # removed since they are not supposed to be used anyway.
        if self.group_id in DEACTIVATED_LEGACY_IDS and not self.pk:
            raise ValidationError(f'Legacy ID {self.group_id} is not allowed')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def active_groups(self):
        return PromotedGroup.objects.filter(active=True)

    @classmethod
    def badged_groups(self):
        return PromotedGroup.active_groups().filter(badged=True)


class PromotedAddon(ModelBase):
    APPLICATION_CHOICES = ((None, 'All Applications'),) + APPS_CHOICES
    group_id = models.SmallIntegerField(
        choices=PROMOTED_GROUP_CHOICES,
        default=PROMOTED_GROUP_CHOICES.NOT_PROMOTED,
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
        return PROMOTED_GROUPS_BY_ID.get(
            self.group_id, PROMOTED_GROUPS_BY_ID[PROMOTED_GROUP_CHOICES.NOT_PROMOTED]
        )

    @property
    def all_applications(self):
        application = APP_IDS.get(self.application_id)
        return [application] if application else [app for app in APP_USAGE]

    @property
    def approved_applications(self):
        """The applications that the current promoted group is approved for.
        Only listed versions are considered."""
        if (
            self.group.id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
            or not self.addon.current_version
        ):
            return []
        return self._get_approved_applications_for_version(self.addon.current_version)

    def _get_approved_applications_for_version(self, version):
        group = self.group
        all_apps = self.all_applications
        if not group.listed_pre_review:
            return all_apps
        return [
            app
            for group_, app in version.approved_for_groups
            if group_ == group and app in all_apps
        ]

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

        The current version will be signed for approval."""

        if not self.addon.current_version:
            return
        self.approve_for_version(self.addon.current_version)

    def save(self, *args, **kwargs):
        due_date = kwargs.pop('_due_date', None)

        super().save(*args, **kwargs)

        if (
            self.group.immediate_approval
            and self.approved_applications != self.all_applications
        ):
            self.approve_for_addon()
        elif self.group.flag_for_human_review:
            self.addon.set_needs_human_review_on_latest_versions(
                due_date=due_date,
                reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP,
            )


# TODO: Drop Promotion suffix after dropping PromotedAddon table
class PromotedAddonPromotion(ModelBase):
    promoted_group = models.ForeignKey(
        PromotedGroup,
        on_delete=models.CASCADE,
        null=False,
        help_text='Can be set to Not Promoted to disable promotion without '
        'deleting it.  Note: changing the group does *not* change '
        'approvals of versions.',
    )
    addon = models.ForeignKey(
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
        choices=APPS_CHOICES,
        null=False,
        verbose_name='Application',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('addon', 'application_id'),
                name='unique_promoted_addon_application',
            ),
        ]

    def __str__(self):
        return f'{self.promoted_group.name} - {self.addon} - {self.application.short}'

    @property
    def application(self):
        return APP_IDS.get(self.application_id)


class PromotedTheme(PromotedAddon):
    """A wrapper around PromotedAddon to use for themes in the featured
    collection."""

    class Meta(PromotedAddon.Meta):
        proxy = True

    @property
    def approved_applications(self):
        if (
            self.group.id == PROMOTED_GROUP_CHOICES.NOT_PROMOTED
            or not self.addon.current_version
        ):
            return []
        return self.all_applications

    def save(self, *args, **kwargs):
        raise NotImplementedError


class PromotedApproval(ModelBase):
    group_id = models.SmallIntegerField(
        choices=PROMOTED_GROUP_CHOICES, null=True, verbose_name='Group'
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
        return f'{self.get_group_id_display()} - {self.version.addon}: {self.version}'

    @property
    def application(self):
        return APP_IDS.get(self.application_id)


class PromotedAddonVersion(ModelBase):
    """A join table between a promoted group, version and application id.
    This model represents an approved promotion for a specific version of an addon
    on a specific application. We can granularly control which approvals are available
    per version and application combination, store additional metadata and maintain
    a clear audit trail of what has been approved and when."""

    promoted_group = models.ForeignKey(
        PromotedGroup,
        on_delete=models.CASCADE,
        null=False,
        related_name='promoted_versions',
    )
    application_id = models.SmallIntegerField(
        choices=APPS_CHOICES, null=False, verbose_name='Application'
    )
    version = models.ForeignKey(
        Version, on_delete=models.CASCADE, null=False, related_name='promoted_versions'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('promoted_group', 'application_id', 'version'),
                name='unique_promoted_addon_version',
            ),
        ]

    def __str__(self):
        return f'{self.promoted_group.name} - {self.version} - {self.application.short}'

    @property
    def application(self):
        return APP_IDS.get(self.application_id)


@receiver(
    models.signals.post_save, sender=PromotedAddon, dispatch_uid='addons.search.index'
)
def update_es_for_promoted(sender, instance, **kw):
    from olympia.addons.models import update_search_index

    # Update ES because Addon.promoted depends on it.
    update_search_index(sender=sender, instance=instance.addon, **kw)


@receiver(
    models.signals.post_save,
    sender=PromotedApproval,
    dispatch_uid='addons.search.index',
)
def update_es_for_promoted_approval(sender, instance, **kw):
    update_es_for_promoted(sender=sender, instance=instance.version, **kw)


@receiver(
    [models.signals.post_save, models.signals.post_delete],
    sender=PromotedAddon,
    dispatch_uid='addons.sync_promoted.promoted_addon',
)
def promoted_addon_to_promoted_addon_promotion(sender, instance, signal, **kw):
    from olympia.promoted.signals import promoted_addon_to_promoted_addon_promotion

    promoted_addon_to_promoted_addon_promotion(signal=signal, instance=instance)


@receiver(
    [models.signals.post_save, models.signals.post_delete],
    sender=PromotedApproval,
    dispatch_uid='addons.sync_promoted.promoted_approval',
)
def promoted_approval_to_promoted_addon_version(sender, instance, signal, **kw):
    from olympia.promoted.signals import promoted_approval_to_promoted_addon_version

    promoted_approval_to_promoted_addon_version(signal=signal, instance=instance)
