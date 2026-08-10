from django.db import models
from django.dispatch import receiver

from olympia.abuse.models import ManagerBase
from olympia.addons.models import Addon
from olympia.amo.models import BaseQuerySet, ModelBase
from olympia.constants.applications import APP_IDS, APPS_CHOICES
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.models import Version


class PromotedGroupQuerySet(BaseQuerySet):
    def __getattr__(self, attribute):
        if hasattr(self.model, attribute):
            # Iterating over self here is better than doing a
            # .values_list(attribute, flat=True) everytime since the queryset
            # results will be cached if accessed multiple times for different
            # properties. There is a slight cost in instantiating the
            # PromotedGroup objects for add-ons with multiple of them but it's
            # negligible and fairly rare.
            return [getattr(obj, attribute) for obj in self]
        raise AttributeError(f'PromotedGroup has no attribute: {attribute}')

    @property
    def name(self):
        return ', '.join(self.__getattr__('name'))


class PromotedGroupManager(ManagerBase):
    _queryset_class = PromotedGroupQuerySet

    def all_for(self, addon):
        return self.get_queryset().filter(promotedaddon__addon=addon).distinct()

    def approved_for(self, addon):
        if not addon.current_version:
            return self.none()
        approved_promotions = addon.approved_promotions().values_list(
            'promoted_group_id', flat=True
        )
        return self.all_for(addon=addon).filter(id__in=approved_promotions)


class PromotedGroup(models.Model):
    """A promotion group defining the promotion rules for add-ons.
    NOTE: This model replaces the legacy PromotedClass and its constants
    """

    name = models.CharField(
        max_length=255, help_text='Human-readable name for the promotion group.'
    )
    api_name = models.CharField(
        max_length=100,
        help_text=(
            'Programmatic API name for the promotion group - be careful with changes '
            'as some api_names are referenced in constants. If the group is public, '
            'changing this value will trigger a reindex of all add-ons in this group.'
        ),
        unique=True,
    )
    search_ranking_bump = models.FloatField(
        help_text=(
            'For public groups, boost value used to influence search ranking for '
            'add-ons in this group. '
            'Changing this value will trigger a reindex for those add-ons.'
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
        help_text=(
            'Specifies if the add-on receives a badge upon promotion. '
            'Changes require a patch to update constants.'
        ),
    )
    autograph_signing_states = models.JSONField(
        blank=True,
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
    is_public = models.BooleanField(
        default=True,
        help_text=(
            'Marks whether this promotion group is public (accessible via the API). '
            'Changing this value will trigger a reindex of all add-ons in this group.'
        ),
    )
    objects = PromotedGroupManager()

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        pre_save = None if not self.pk else PromotedGroup.objects.get(pk=self.pk)
        super().save(*args, **kwargs)
        if pre_save is not None and (
            pre_save.is_public != self.is_public
            or self.is_public
            and (
                pre_save.search_ranking_bump != self.search_ranking_bump
                or pre_save.api_name != self.api_name
            )
        ):
            from olympia.addons.tasks import index_addons

            addon_ids = list(
                self.promotedaddon_set.values_list('addon_id', flat=True).distinct()
            )
            if addon_ids:
                index_addons.delay(addon_ids)

    def delete(self, *args, **kwargs):
        addon_ids = (
            list(self.promotedaddon_set.values_list('addon_id', flat=True).distinct())
            if self.is_public
            else []
        )
        super().delete(*args, **kwargs)

        if addon_ids:
            from olympia.addons.tasks import index_addons

            index_addons.delay(addon_ids)


class PromotedAddon(ModelBase):
    promoted_group = models.ForeignKey(
        PromotedGroup,
        on_delete=models.CASCADE,
        null=False,
        help_text='The promotion can be deleted to disable promotion.'
        'Note: changing the group does *not* change '
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
        related_name='promotedaddon',
    )
    application_id = models.SmallIntegerField(
        choices=APPS_CHOICES,
        null=False,
        verbose_name='Application',
    )

    class Meta:
        db_table = 'promoted_promotedaddonpromotion'
        constraints = [
            models.UniqueConstraint(
                fields=('addon', 'promoted_group', 'application_id'),
                name='unique_addon_promotion_application',
            ),
        ]

    def __str__(self):
        return f'{self.promoted_group.name} - {self.addon} - {self.application.short}'

    @property
    def application(self):
        return APP_IDS.get(self.application_id)

    @property
    def approved_applications(self):
        """The applications that the current promoted group is approved for,
        for the current version."""
        return self.addon.approved_applications_for(self.promoted_group)

    def approve_for_version(self, version):
        """Create PromotedApprovals for current applications
        in the current promoted group."""
        for app in self.addon.all_applications_for(promoted_group=self.promoted_group):
            PromotedApproval.objects.update_or_create(
                promoted_group=self.promoted_group,
                application_id=app.id,
                version=version,
            )

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
            self.pk is None
            and self.promoted_group.immediate_approval
            and self.approved_applications != self.addon.all_applications
        ):
            self.approve_for_addon()
        elif self.promoted_group.flag_for_human_review:
            self.addon.set_needs_human_review_on_latest_versions(
                due_date=due_date,
                reason=NeedsHumanReview.REASONS.ADDED_TO_PROMOTED_GROUP,
            )


class PromotedApprovalQuerySet(BaseQuerySet):
    @property
    def approved_applications(self):
        """The applications that the current promoted group is approved for."""
        app_ids = self.values_list('application_id', flat=True).distinct()
        return [APP_IDS[id] for id in app_ids]


class PromotedApprovalManager(ManagerBase):
    _queryset_class = PromotedApprovalQuerySet


class PromotedApproval(ModelBase):
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
    objects = PromotedApprovalManager()

    class Meta:
        db_table = 'promoted_promotedaddonversion'
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
    models.signals.post_save,
    sender=PromotedAddon,
    dispatch_uid='addons.search.index',
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
def update_es_for_promoted_addon_version(sender, instance, **kw):
    update_es_for_promoted(sender=sender, instance=instance.version, **kw)
