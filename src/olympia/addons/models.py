import hashlib
import itertools
import os
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.db.models import (
    Exists,
    F,
    Max,
    Min,
    OuterRef,
    Q,
    Subquery,
    signals as dbsignals,
)
from django.db.models.functions import Coalesce, Greatest
from django.dispatch import receiver
from django.urls import reverse
from django.utils import translation
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _, trans_real

import waffle
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import activity, amo, core
from olympia.addons.utils import generate_addon_guid
from olympia.amo.decorators import use_primary_db
from olympia.amo.enum import EnumChoices
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import (
    BasePreview,
    BaseQuerySet,
    FilterableManyToManyField,
    LongNameIndex,
    ManagerBase,
    ModelBase,
    OnChangeMixin,
    SaveUpdateMixin,
)
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.utils import (
    StopWatch,
    attach_trans_dict,
    find_language,
    send_mail,
    slugify,
    sorted_groupby,
    to_language,
)
from olympia.constants.blocklist import REASON_ADDON_DELETED
from olympia.constants.browsers import BROWSERS
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.constants.promoted import (
    PROMOTED_GROUP_CHOICES,
)
from olympia.constants.reviewers import REPUTATION_CHOICES
from olympia.files.models import File
from olympia.files.utils import extract_translations, resolve_i18n_message
from olympia.ratings.models import Rating
from olympia.tags.models import Tag
from olympia.translations.fields import (
    NoURLsField,
    PurifiedMarkdownField,
    TranslatedField,
    save_signal,
)
from olympia.translations.models import Translation
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.models import (
    Version,
    VersionPreview,
    VersionReviewerFlags,
    inherit_due_date_if_nominated,
)
from olympia.versions.utils import get_review_due_date
from olympia.zadmin.models import get_config

from . import signals


log = olympia.core.logger.getLogger('z.addons')


MAX_SLUG_INCREMENT = 999
SLUG_INCREMENT_SUFFIXES = set(range(1, MAX_SLUG_INCREMENT + 1))
GUID_REUSE_FORMAT = 'guid-reused-by-pk-{}'


class GuidAlreadyDeniedError(RuntimeError):
    pass


def get_random_slug():
    """Return a 20 character long random string"""
    return ''.join(str(uuid.uuid4()).split('-')[:-1])


def clean_slug(instance, slug_field='slug'):
    """Cleans a model instance slug.

    This strives to be as generic as possible but is only used
    by Add-ons at the moment.

    :param instance: The instance to clean the slug for.
    :param slug_field: The field where to get the currently set slug from.
    """
    slug = getattr(instance, slug_field, None) or instance.name

    if not slug:
        # Initialize the slug with what we have available: a name translation
        # or in last resort a random slug.
        translations = Translation.objects.filter(id=instance.name_id)
        if translations.exists():
            slug = translations[0]

    max_length = instance._meta.get_field(slug_field).max_length
    # We have to account for slug being reduced to '' by slugify
    slug = slugify(slug or '')[:max_length] or get_random_slug()

    if DeniedSlug.blocked(slug):
        slug = slug[: max_length - 1] + '~'

    # The following trick makes sure we are using a manager that returns
    # all the objects, as otherwise we could have a slug clash on our hands.
    # Eg with the "Addon.objects" manager, which doesn't list deleted addons,
    # we could have a "clean" slug which is in fact already assigned to an
    # already existing (deleted) addon. Also, make sure we use the base class.
    manager = models.Manager()
    manager.model = instance._meta.proxy_for_model or instance.__class__

    qs = manager.values_list(slug_field, flat=True)  # Get list of all slugs.
    if instance.id:
        qs = qs.exclude(pk=instance.id)  # Can't clash with itself.

    # We first need to make sure there's a clash, before trying to find a
    # suffix that is available. Eg, if there's a "foo-bar" slug, "foo" is still
    # available.
    clash = qs.filter(**{slug_field: slug})

    if clash.exists():
        max_postfix_length = len(str(MAX_SLUG_INCREMENT))

        slug = slugify(slug)[: max_length - max_postfix_length]

        # There is a clash, so find a suffix that will make this slug unique.
        lookup = {'%s__startswith' % slug_field: slug}
        clashes = qs.filter(**lookup)

        prefix_len = len(slug)
        used_slug_numbers = [value[prefix_len:] for value in clashes]

        # find the next free slug number
        slug_numbers = {int(i) for i in used_slug_numbers if i.isdigit()}
        unused_numbers = SLUG_INCREMENT_SUFFIXES - slug_numbers

        if unused_numbers:
            num = min(unused_numbers)
        elif max_length is None:
            num = max(slug_numbers) + 1
        else:
            # This could happen. The current implementation (using
            # ``[:max_length -2]``) only works for the first 100 clashes in the
            # worst case (if the slug is equal to or longuer than
            # ``max_length - 2`` chars).
            # After that, {verylongslug}-100 will be trimmed down to
            # {verylongslug}-10, which is already assigned, but it's the last
            # solution tested.
            raise RuntimeError(f'No suitable slug increment for {slug} found')

        slug = f'{slug}{num}'

    setattr(instance, slug_field, slug)

    return instance


def first_pending_version_transformer(addons):
    """Transformer used to attach the special first_pending_version field on
    addons, used in reviewer queues."""
    version_ids = {addon.first_version_id for addon in addons}
    versions = {
        version.id: version
        for version in Version.unfiltered.filter(id__in=version_ids)
        .no_transforms()
        .select_related('autoapprovalsummary')
    }
    for addon in addons:
        addon.first_pending_version = versions.get(addon.first_version_id)


class AddonQuerySet(BaseQuerySet):
    def id_or_slug(self, val):
        """Get add-ons by id or slug."""
        if isinstance(val, str) and not val.isdigit():
            return self.filter(slug=val)
        return self.filter(id=val)

    def public(self):
        """Get approved add-ons only"""
        return self.filter(self.valid_q(amo.APPROVED_STATUSES))

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.filter(self.valid_q(amo.VALID_ADDON_STATUSES))

    def not_disabled_by_mozilla(self):
        """Get all add-ons not disabled by Mozilla."""
        return self.exclude(status=amo.STATUS_DISABLED)

    def valid_q(self, statuses):
        """
        Return a Q object that selects a valid Addon with the given statuses.

        An add-on is valid if not disabled and has a current version.
        """
        return Q(
            _current_version__isnull=False, disabled_by_user=False, status__in=statuses
        )


class AddonManager(ManagerBase):
    _queryset_class = AddonQuerySet

    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.include_deleted:
            qs = qs.exclude(status=amo.STATUS_DELETED)
        return qs.transform(Addon.transformer)

    def id_or_slug(self, val):
        """Get add-ons by id or slug."""
        return self.get_queryset().id_or_slug(val)

    def public(self):
        """Get public add-ons only"""
        return self.get_queryset().public()

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.get_queryset().valid()

    def not_disabled_by_mozilla(self):
        """Get all add-ons not disabled by Mozilla."""
        return self.get_queryset().not_disabled_by_mozilla()

    def get_base_queryset_for_queue(
        self,
        admin_reviewer=False,
        content_review=False,
        theme_review=False,
        select_related_fields_for_listed=True,
    ):
        qs = (
            self.get_queryset()
            # We don't want the default transformer, it does too much, and
            # crucially, it prevents the
            # select_related('_current_version__autoapprovalsummary') from
            # working, because it overrides the _current_version with the one
            # it fetches. We want translations though, but only for the name.
            .only_translations()
            .defer(*[x.name for x in Addon._meta.translated_fields if x.name != 'name'])
        )
        # Useful joins to avoid extra queries.
        select_related_fields = [
            'reviewerflags',
            'addonapprovalscounter',
        ]
        if select_related_fields_for_listed:
            # Most listed queues need these to avoid extra queries because
            # they display the score, flags, promoted status, link to files
            # etc.
            select_related_fields.extend(
                (
                    '_current_version',
                    '_current_version__autoapprovalsummary',
                    '_current_version__file',
                    '_current_version__reviewerflags',
                )
            )
        qs = qs.select_related(*select_related_fields)

        if theme_review and not admin_reviewer:
            qs = qs.exclude(reviewerflags__needs_admin_theme_review=True)
        return qs

    def get_queryset_for_pending_queues(
        self,
        *,
        admin_reviewer=False,
        theme_review=False,
        show_temporarily_delayed=True,
        show_only_upcoming=False,
        due_date_reasons_choices=None,
    ):
        filters = {
            'type__in': amo.GROUP_TYPE_THEME if theme_review else amo.GROUP_TYPE_ADDON,
            'versions__due_date__isnull': False,
        }
        qs = self.get_base_queryset_for_queue(
            admin_reviewer=admin_reviewer,
            theme_review=theme_review,
            # These queues merge unlisted and listed together, so the
            # select_related() for listed fields don't make sense.
            select_related_fields_for_listed=False,
        )
        versions_due_qs = (
            Version.unfiltered.filter(due_date__isnull=False, addon=OuterRef('pk'))
            .no_transforms()
            .order_by('due_date')
        )
        if show_only_upcoming:
            days = get_config(amo.config_keys.UPCOMING_DUE_DATE_CUT_OFF_DAYS)
            upcoming_cutoff_date = get_review_due_date(default_days=days)
            versions_due_qs = versions_due_qs.filter(due_date__lte=upcoming_cutoff_date)
        if not show_temporarily_delayed:
            # If we were asked not to show temporarily delayed, we need to
            # exclude versions from the channel of the corresponding addon auto
            # approval delay flag.This way, we keep showing the add-on if it
            # has other versions that would not be in that channel.
            unlisted_delay_flag_field = (
                'addon__reviewerflags__auto_approval_delayed_until_unlisted'
            )
            listed_delay_flag_field = (
                'addon__reviewerflags__auto_approval_delayed_until'
            )
            versions_due_qs = versions_due_qs.exclude(
                Q(
                    Q(channel=amo.CHANNEL_UNLISTED)
                    & Q(**{f'{unlisted_delay_flag_field}__isnull': False})
                    & ~Q(**{unlisted_delay_flag_field: datetime.max})
                )
                | Q(
                    Q(channel=amo.CHANNEL_LISTED)
                    & Q(**{f'{listed_delay_flag_field}__isnull': False})
                    & ~Q(**{listed_delay_flag_field: datetime.max})
                )
            )
        version_subqs = versions_due_qs.all()
        if due_date_reasons_choices:
            versions_filter = Q(
                versions__needshumanreview__reason__in=due_date_reasons_choices.values,
                versions__needshumanreview__is_active=True,
            )
            version_subqs = version_subqs.filter(
                needshumanreview__reason__in=due_date_reasons_choices.values,
                needshumanreview__is_active=True,
            )
        else:
            versions_filter = None
        qs = (
            qs.filter(**filters)
            .annotate(
                # We need both first_version_due_date and first_version_id to
                # be set and have the same behavior. The former is used for
                # grouping (hence the Min()) and provides a way for callers to
                # sort this queryset by due date, the latter to filter add-ons
                # matching the reasons we care about and to instantiate the
                # right Version in first_pending_version_transformer().
                first_version_due_date=Min(
                    'versions__due_date', filter=versions_filter
                ),
                first_version_id=Subquery(version_subqs.values('pk')[:1]),
                **{
                    name: Exists(versions_due_qs.filter(q))
                    for name, q in (
                        Version.unfiltered.get_due_date_reason_q_objects().items()
                    )
                },
            )
            .filter(first_version_id__isnull=False)
            .transform(first_pending_version_transformer)
        )
        return qs

    def get_content_review_queue(self, admin_reviewer=False):
        """Return a queryset of Addon objects that need content review."""
        qs = (
            self.get_base_queryset_for_queue(
                admin_reviewer=admin_reviewer, content_review=True
            )
            .valid()
            .filter(
                _current_version__reviewerflags__pending_rejection__isnull=True,
                # Only content review extensions and dictionaries. See
                # https://github.com/mozilla/addons-server/issues/11796 &
                # https://github.com/mozilla/addons-server/issues/12065
                type__in=(amo.ADDON_EXTENSION, amo.ADDON_DICT),
            )
            .exclude(
                addonapprovalscounter__content_review_status__in=(
                    AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.COMPLETE
                )
            )
            .order_by('created')
        )
        return qs

    def get_base_extensions_queue_with_non_disabled_versions(
        self, *q_filters, admin_reviewer=False
    ):
        """Return base queryset for all queues that look at extensions with non
        disabled versions - typically scanners queues, where anything could be
        flagged, approved or waiting for review."""
        return (
            self.get_base_queryset_for_queue(admin_reviewer=admin_reviewer)
            .filter(
                # Only extensions to avoid looking at themes etc, which slows
                # the query down.
                Q(type=amo.ADDON_EXTENSION),
                # All valid statuses, plus incomplete as well because the add-on could
                # be purely unlisted (so we can't use valid_q(), which filters out
                # current_version=None). We know the add-ons are likely to have a
                # version since they were flagged, so returning incomplete ones
                # is acceptable.
                Q(status__in=amo.VALID_ADDON_STATUSES + (amo.STATUS_NULL,)),
                Q(versions__file__status__in=amo.VALID_FILE_STATUSES),
                Q(versions__reviewerflags__pending_rejection__isnull=True),
                *q_filters,
            )
            .order_by('created')
            # There could be several versions matching for a single add-on so
            # we need a distinct.
            .distinct()
        )

    def get_pending_rejection_queue(self, admin_reviewer=False):
        versions_pending_rejection_qs = (
            Version.unfiltered.filter(reviewerflags__pending_rejection__isnull=False)
            .no_transforms()
            .order_by('reviewerflags__pending_rejection')
        )
        return (
            self.get_base_queryset_for_queue(
                select_related_fields_for_listed=False, admin_reviewer=admin_reviewer
            )
            .filter(versions__reviewerflags__pending_rejection__isnull=False)
            .annotate(
                first_version_pending_rejection_date=Min(
                    'versions__reviewerflags__pending_rejection'
                ),
                first_version_id=Subquery(
                    versions_pending_rejection_qs.filter(addon=OuterRef('pk')).values(
                        'pk'
                    )[:1]
                ),
            )
            .filter(first_version_id__isnull=False)
            .transform(first_pending_version_transformer)
        )


class Addon(OnChangeMixin, ModelBase):
    id = PositiveAutoField(primary_key=True)
    STATUS_CHOICES = amo.STATUS_CHOICES_ADDON

    guid = models.CharField(max_length=255, unique=True, null=True)
    slug = models.CharField(max_length=30, unique=True, null=True, blank=True)
    name = TranslatedField(max_length=50)
    default_locale = models.CharField(
        max_length=10, default=settings.LANGUAGE_CODE, db_column='defaultlocale'
    )

    type = models.PositiveIntegerField(
        choices=amo.ADDON_TYPE.items(),
        db_column='addontype_id',
        default=amo.ADDON_EXTENSION,
    )
    status = models.PositiveIntegerField(
        choices=STATUS_CHOICES.items(), default=amo.STATUS_NULL
    )
    icon_type = models.CharField(max_length=25, blank=True, db_column='icontype')
    icon_hash = models.CharField(max_length=8, blank=True, null=True)
    homepage = TranslatedField(max_length=255)
    support_email = TranslatedField(db_column='supportemail', max_length=100)
    support_url = TranslatedField(db_column='supporturl', max_length=255)
    description = PurifiedMarkdownField(short=False, max_length=15000)

    summary = NoURLsField(max_length=250)
    developer_comments = PurifiedMarkdownField(
        db_column='developercomments', max_length=3000
    )
    eula = PurifiedMarkdownField(max_length=350000)
    privacy_policy = PurifiedMarkdownField(db_column='privacypolicy', max_length=150000)

    average_rating = models.FloatField(
        max_length=255, default=0, null=True, db_column='averagerating'
    )
    bayesian_rating = models.FloatField(default=0, db_column='bayesianrating')
    total_ratings = models.PositiveIntegerField(default=0, db_column='totalreviews')
    text_ratings_count = models.PositiveIntegerField(
        default=0, db_column='textreviewscount'
    )
    weekly_downloads = models.PositiveIntegerField(
        default=0, db_column='weeklydownloads'
    )
    hotness = models.FloatField(default=0)

    average_daily_users = models.PositiveIntegerField(default=0)

    last_updated = models.DateTimeField(
        null=True, help_text='Last time this add-on had a file/version update'
    )

    disabled_by_user = models.BooleanField(default=False, db_column='inactive')

    target_locale = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='For dictionaries and language packs. Identifies the '
        'language and, optionally, region that this add-on is '
        'written for. Examples: en-US, fr, and de-AT',
    )

    contributions = models.URLField(max_length=255, blank=True)

    authors = FilterableManyToManyField(
        'users.UserProfile',
        through='AddonUser',
        related_name='addons',
        q_filter=~Q(addonuser__role=amo.AUTHOR_ROLE_DELETED),
    )

    _current_version = models.ForeignKey(
        Version,
        db_column='current_version',
        related_name='+',
        null=True,
        on_delete=models.SET_NULL,
    )

    is_experimental = models.BooleanField(default=False, db_column='experimental')
    reputation = models.SmallIntegerField(
        default=0,
        null=True,
        choices=REPUTATION_CHOICES.items(),
        help_text='The higher the reputation value, the further down the '
        'add-on will be in the auto-approved review queue. '
        'A value of 0 has no impact',
    )
    requires_payment = models.BooleanField(default=False)

    unfiltered = AddonManager(include_deleted=True)
    objects = AddonManager()

    class Meta:
        db_table = 'addons'
        # This is very important:
        # The default base manager will be used for relations like
        # `version.addon`. We thus want one that is NOT filtered in any case,
        # we don't want a 500 if the addon is not found (because it has the
        # status amo.STATUS_DELETED for example).
        # The CLASS of the one configured here will also be used for "many to
        # many relations" like `collection.addons`. In that case, we do want
        # the filtered version by default, to make sure we're not displaying
        # stuff by mistake. You thus want the filtered one configured
        # as `base_manager_name`.
        # We don't control the instantiation, but AddonManager sets
        # include_deleted to False by default, so filtering is enabled by
        # default.
        base_manager_name = 'unfiltered'
        indexes = [
            models.Index(fields=('bayesian_rating',), name='bayesianrating'),
            models.Index(fields=('created',), name='addons_created_idx'),
            models.Index(fields=('_current_version',), name='current_version'),
            models.Index(fields=('disabled_by_user',), name='inactive'),
            models.Index(fields=('hotness',), name='hotness_idx'),
            models.Index(fields=('last_updated',), name='last_updated'),
            models.Index(fields=('modified',), name='modified_idx'),
            models.Index(fields=('status',), name='addons_status_idx'),
            models.Index(fields=('target_locale',), name='target_locale'),
            models.Index(fields=('type',), name='addontype_id'),
            models.Index(fields=('weekly_downloads',), name='weeklydownloads_idx'),
            models.Index(fields=('average_daily_users', 'type'), name='adus_type_idx'),
            models.Index(fields=('bayesian_rating', 'type'), name='rating_type_idx'),
            models.Index(fields=('created', 'type'), name='created_type_idx'),
            models.Index(fields=('last_updated', 'type'), name='last_updated_type_idx'),
            models.Index(fields=('modified', 'type'), name='modified_type_idx'),
            models.Index(
                fields=('type', 'status', 'disabled_by_user'),
                name='type_status_inactive_idx',
            ),
            models.Index(
                fields=('weekly_downloads', 'type'), name='downloads_type_idx'
            ),
            models.Index(
                fields=('type', 'status', 'disabled_by_user', '_current_version'),
                name='visible_idx',
            ),
            models.Index(fields=('name', 'status', 'type'), name='name_2'),
        ]

    def __str__(self):
        return f'{self.id}: {self.name}'

    def save(self, **kw):
        self.clean_slug()
        super().save(**kw)

    @use_primary_db
    def clean_slug(self, slug_field='slug'):
        if self.status == amo.STATUS_DELETED:
            return

        clean_slug(self, slug_field)

    def force_disable(self, skip_activity_log=False):
        from olympia.addons.tasks import delete_all_addon_media_with_backup
        from olympia.reviewers.models import NeedsHumanReview

        if not skip_activity_log:
            activity.log_create(amo.LOG.FORCE_DISABLE, self)
        log.info(
            'Addon "%s" status force-changed to: %s', self.slug, amo.STATUS_DISABLED
        )
        self.update(status=amo.STATUS_DISABLED)
        # https://github.com/mozilla/addons-server/issues/13194
        Addon.disable_all_files([self], File.STATUS_DISABLED_REASONS.ADDON_DISABLE)
        self.update_version()
        # https://github.com/mozilla/addons-server/issues/20507
        NeedsHumanReview.objects.filter(
            version__in=self.versions(manager='unfiltered_for_relations').all()
        ).update(is_active=False)
        self.update_all_due_dates()

        delete_all_addon_media_with_backup.delay(self.pk)

    def force_enable(self, skip_activity_log=False):
        from olympia.addons.tasks import restore_all_addon_media_from_backup

        if not skip_activity_log:
            activity.log_create(amo.LOG.FORCE_ENABLE, self)
        log.info(
            'Addon "%s" status force-changed to: %s', self.slug, amo.STATUS_APPROVED
        )
        qs = File.objects.disabled_that_would_be_renabled_with_addon().filter(
            version__addon=self
        )
        qs.update(status=F('original_status'))
        qs.update(
            status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
            original_status=amo.STATUS_NULL,
        )
        self.update(status=amo.STATUS_APPROVED)
        # Call update_status() to fix the status if the add-on is not actually
        # in a state that allows it to be public.
        self.update_status()

        restore_all_addon_media_from_backup.delay(self.pk)

    def deny_resubmission(self):
        if not self.guid:
            raise RuntimeError('No GUID on this add-on')
        if self.is_guid_denied:
            raise GuidAlreadyDeniedError('GUID already denied')

        activity.log_create(amo.LOG.DENIED_GUID_ADDED, self)
        log.info('Deny resubmission for addon "%s"', self.slug)
        DeniedGuid.objects.create(guid=self.guid)

    def allow_resubmission(self):
        if not self.is_guid_denied:
            raise RuntimeError('GUID already allowed')

        activity.log_create(amo.LOG.DENIED_GUID_DELETED, self)
        log.info('Allow resubmission for addon "%s"', self.slug)
        DeniedGuid.objects.filter(guid=self.guid).delete()

    @classmethod
    def disable_all_files(cls, addons, reason):
        qs = File.objects.filter(version__addon__in=addons).exclude(
            status=amo.STATUS_DISABLED
        )
        qs.update(original_status=F('status'))
        qs.update(
            status=amo.STATUS_DISABLED,
            status_disabled_reason=reason,
        )

    def set_needs_human_review_on_latest_versions(
        self,
        *,
        reason,
        due_date=None,
        ignore_reviewed=True,
        unique_reason=False,
        skip_activity_log=False,
    ):
        set_listed = self._set_needs_human_review_on_latest_signed_version(
            channel=amo.CHANNEL_LISTED,
            due_date=due_date,
            reason=reason,
            ignore_reviewed=ignore_reviewed,
            unique_reason=unique_reason,
            skip_activity_log=skip_activity_log,
        )
        set_unlisted = self._set_needs_human_review_on_latest_signed_version(
            channel=amo.CHANNEL_UNLISTED,
            due_date=due_date,
            reason=reason,
            ignore_reviewed=ignore_reviewed,
            unique_reason=unique_reason,
            skip_activity_log=skip_activity_log,
        )
        return [ver for ver in (set_listed, set_unlisted) if ver]

    def _set_needs_human_review_on_latest_signed_version(
        self,
        *,
        channel,
        reason,
        due_date=None,
        ignore_reviewed=True,
        unique_reason=False,
        skip_activity_log=False,
    ):
        from olympia.reviewers.models import NeedsHumanReview

        version = (
            self.versions(manager='unfiltered_for_relations')
            .filter(file__is_signed=True, channel=channel)
            .only_translations()
            .first()
        )
        if (
            not version
            or (ignore_reviewed and version.human_review_date)
            or version.needshumanreview_set.filter(
                is_active=True, **({'reason': reason} if unique_reason else {})
            ).exists()
        ):
            return None
        had_due_date_already = bool(version.due_date)
        NeedsHumanReview(version=version, reason=reason).save(
            _no_automatic_activity_log=skip_activity_log
        )
        if not had_due_date_already and due_date:
            # If we have a specific due_date, override the default
            version.reset_due_date(due_date)
        return version

    def versions_triggering_needs_human_review_inheritance(self, channel):
        """Return queryset of Versions belonging to this addon in the specified
        channel that should be considered for due date and NeedsHumanReview
        inheritance."""
        from olympia.reviewers.models import NeedsHumanReview

        reasons_triggering_inheritance = set(NeedsHumanReview.REASONS.values) - set(
            NeedsHumanReview.REASONS.NO_DUE_DATE_INHERITANCE.values
        )
        return self.versions(manager='unfiltered_for_relations').filter(
            channel=channel,
            needshumanreview__is_active=True,
            needshumanreview__reason__in=reasons_triggering_inheritance,
        )

    @property
    def is_guid_denied(self):
        return DeniedGuid.objects.filter(guid=self.guid).exists()

    def is_soft_deleteable(self):
        return self.status or Version.unfiltered.filter(addon=self).exists()

    def _prepare_deletion_email(self, msg, reason):
        user = core.get_user()
        # Don't localize email to admins, use 'en-US' always.
        with translation.override(settings.LANGUAGE_CODE):
            # The types are lazy translated in apps/constants/base.py.
            atype = amo.ADDON_TYPE.get(self.type, 'unknown').upper()
        context = {
            'atype': atype,
            'authors': [u.email for u in self.authors.all()],
            'adu': self.average_daily_users,
            'guid': self.guid,
            'id': self.id,
            'msg': msg,
            'reason': reason,
            'name': self.name,
            'slug': self.slug,
            'weekly_downloads': self.weekly_downloads,
            'url': jinja_helpers.absolutify(self.get_url_path()),
            'user_str': (
                f'{user.name}, {user.email} ({user.id})' if user else 'Unknown'
            ),
        }

        email_msg = (
            """
        The following %(atype)s was deleted.
        %(atype)s: %(name)s
        URL: %(url)s
        DELETED BY: %(user_str)s
        ID: %(id)s
        GUID: %(guid)s
        AUTHORS: %(authors)s
        WEEKLY DOWNLOADS: %(weekly_downloads)s
        AVERAGE DAILY USERS: %(adu)s
        NOTES: %(msg)s
        REASON GIVEN BY USER FOR DELETION: %(reason)s
        """
            % context
        )
        log.info('Sending delete email for %(atype)s %(id)s' % context)
        subject = 'Deleting %(atype)s %(slug)s (%(id)d)' % context
        return subject, email_msg

    @transaction.atomic
    def delete(self, *, msg='', reason='', send_delete_email=True):
        # To avoid a circular import
        from olympia.versions import tasks as version_tasks

        from . import tasks

        # Check for soft deletion path. Happens only if the addon status isn't
        # 0 (STATUS_INCOMPLETE) with no versions.
        soft_deletion = self.is_soft_deleteable()
        if soft_deletion and self.status == amo.STATUS_DELETED:
            # We're already done.
            return

        id = self.id

        # Fetch previews before deleting the addon instance, so that we can
        # pass the list of files to delete to the delete_preview_files task
        # after the addon is deleted.
        previews = list(
            Preview.objects.filter(addon__id=id).values_list('id', flat=True)
        )
        version_previews = list(
            VersionPreview.objects.filter(version__addon__id=id).values_list(
                'id', flat=True
            )
        )

        if soft_deletion:
            # /!\ If we ever stop using soft deletion, and remove this code, we
            # need to make sure that the logs created below aren't cascade
            # deleted!

            log.info('Deleting add-on: %s' % self.id)

            if send_delete_email:
                email_to = [settings.DELETION_EMAIL]
                subject, email_msg = self._prepare_deletion_email(msg, reason)
            else:
                email_to, subject, email_msg = [], '', ''
            # If the add-on was disabled by Mozilla, add the guid to
            #  DeniedGuids to prevent resubmission after deletion.
            if self.status == amo.STATUS_DISABLED:
                try:
                    with transaction.atomic():
                        self.deny_resubmission()
                except RuntimeError:
                    # If the guid is already in DeniedGuids, we are good.
                    pass

            # Update or NULL out various fields.
            models.signals.pre_delete.send(sender=Addon, instance=self)
            for rating in self._ratings.all():
                rating.delete(skip_activity_log=True)
            # We avoid triggering signals for Version & File on purpose to
            # avoid extra work.
            Addon.disable_all_files([self], File.STATUS_DISABLED_REASONS.ADDON_DELETE)

            self.versions.all().update(deleted=True)
            VersionReviewerFlags.objects.filter(version__addon=self).update(
                pending_rejection=None,
                pending_rejection_by=None,
                pending_content_rejection=None,
            )
            # The last parameter is needed to automagically create an AddonLog.
            activity.log_create(amo.LOG.DELETE_ADDON, self.pk, str(self.guid), self)
            self.update(
                status=amo.STATUS_DELETED,
                slug=None,
                _current_version=None,
                modified=datetime.now(),
            )
            models.signals.post_delete.send(sender=Addon, instance=self)

            if send_delete_email:
                send_mail(subject, email_msg, recipient_list=email_to)

            all_versions = list(
                self.versions(manager='unfiltered_for_relations').values_list(
                    'id', flat=True
                )
            )
            if all_versions:
                version_tasks.soft_block_versions.delay(
                    version_ids=all_versions, reason=REASON_ADDON_DELETED
                )
        else:
            # Real deletion path.
            super().delete()

        for preview in previews:
            tasks.delete_preview_files.delay(preview)
        for preview in version_previews:
            version_tasks.delete_preview_files.delay(preview)

        return True

    @classmethod
    def initialize_addon_from_upload(cls, *, data, upload, channel, user):
        timer = StopWatch('addons.models.initialize_addon_from_upload.')
        timer.start()
        fields = [field.name for field in cls._meta.get_fields()]
        guid = data.get('guid')
        if not guid:
            data['guid'] = guid = generate_addon_guid()
        timer.log_interval('1.guids')

        data = cls.resolve_webext_translations(data, upload)
        timer.log_interval('2.resolve_translations')

        if channel == amo.CHANNEL_UNLISTED:
            data['slug'] = get_random_slug()
        timer.log_interval('3.get_random_slug')

        addon = Addon(**{k: v for k, v in data.items() if k in fields})
        timer.log_interval('4.instance_init')

        addon.status = amo.STATUS_NULL
        locale_is_set = (
            addon.default_locale
            and addon.default_locale in settings.AMO_LANGUAGES
            and data.get('default_locale') == addon.default_locale
        )
        if not locale_is_set:
            addon.default_locale = to_language(trans_real.get_language())
        timer.log_interval('5.default_locale')

        # Note: Trying to create an add-on with a guid that is already used
        # will trigger an IntegrityError here, which is fine: we want to
        # prevent the creation in that case and it's too late to handle the
        # error elegantly as we'll likely be in a task - this should happen
        # before, at validation.
        addon.save()
        timer.log_interval('6.addon_save')

        AddonGUID.objects.create(addon=addon, guid=guid)

        AddonUser(addon=addon, user=user).save()
        activity.log_create(amo.LOG.CREATE_ADDON, addon, user=user)
        log.info(f'New addon {addon!r} from {upload!r}')
        timer.log_interval('7.end')
        return addon

    @classmethod
    def from_upload(
        cls,
        upload,
        *,
        selected_apps,
        parsed_data,
        client_info=None,
        channel=amo.CHANNEL_LISTED,
    ):
        """
        Create an Addon instance, a Version and corresponding File(s) from a
        FileUpload, a list of compatible app ids, a channel id and the
        parsed_data generated by parse_addon().

        Note that it's the caller's responsability to ensure the file is valid.
        We can't check for that here because an admin may have overridden the
        validation results.
        """
        assert parsed_data is not None

        addon = cls.initialize_addon_from_upload(
            data=parsed_data, upload=upload, channel=channel, user=upload.user
        )
        Version.from_upload(
            upload=upload,
            addon=addon,
            channel=channel,
            selected_apps=selected_apps,
            parsed_data=parsed_data,
            client_info=client_info,
        )
        return addon

    @classmethod
    def resolve_webext_translations(
        cls,
        data,
        upload,
        *,
        use_default_locale_fallback=True,
        fields=('name', 'homepage', 'summary'),
    ):
        """Resolve all possible translations from an add-on.

        This returns a modified `data` dictionary accordingly with proper
        translations filled in.
        """
        default_locale = find_language(data.get('default_locale'))

        if not default_locale:
            # Don't change anything if we don't meet the requirements
            return data

        # find_language might have expanded short to full locale, so update it.
        data['default_locale'] = default_locale

        messages = extract_translations(upload)

        for field in fields:
            if isinstance(data[field], dict):
                # if the field value is already a localized set of values don't override
                continue
            if messages:
                data[field] = {
                    locale: value
                    for locale in messages
                    if (
                        value := resolve_i18n_message(
                            data[field],
                            locale=locale,
                            default_locale=use_default_locale_fallback
                            and default_locale,
                            messages=messages,
                        )
                    )
                    is not None
                }
            else:
                # If we got a default_locale but no messages then the default_locale has
                # been set via the serializer for a non-localized xpi, so format data
                # correctly so the manifest values are assigned the correct locale.
                data[field] = {default_locale: data[field]}

        return data

    def get_url_path(self, add_prefix=True):
        if not self._current_version_id:
            return ''
        return reverse('addons.detail', args=[self.slug], add_prefix=add_prefix)

    def get_dev_url(self, action='edit', args=None, prefix_only=False):
        args = args or []
        prefix = 'devhub'
        if not prefix_only:
            prefix += '.addons'
        view_name = f'{prefix}.{action}'
        return reverse(view_name, args=[self.slug] + args)

    def get_detail_url(self, action='detail', args=None):
        if args is None:
            args = []
        return reverse('addons.%s' % action, args=[self.slug] + args)

    @property
    def ratings_url(self):
        return reverse('addons.ratings.list', args=[self.slug])

    @property
    def versions_url(self):
        return reverse('addons.versions', args=[self.slug])

    @cached_property
    def listed_authors(self):
        return self.authors.filter(addons=self, addonuser__listed=True).order_by(
            'addonuser__position'
        )

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    @property
    def ratings(self):
        return Rating.objects.filter(addon=self, reply_to=None)

    def language_ascii(self):
        lang = settings.LANGUAGE_URL_MAP.get(
            trans_real.to_language(self.default_locale)
        )
        return settings.ALL_LANGUAGES.get(lang, {}).get('native')

    @property
    def valid_file_statuses(self):
        if self.status == amo.STATUS_APPROVED:
            return [amo.STATUS_APPROVED]
        return amo.VALID_FILE_STATUSES

    def find_latest_non_rejected_listed_version(self):
        """Return the latest non-deleted, non-rejected listed version of an
        add-on, or None.

        Can return a user-disabled or non-approved version.
        """
        return (
            self.versions.filter(channel=amo.CHANNEL_LISTED)
            .not_rejected()
            .order_by('pk')
            .last()
        )

    def find_latest_public_listed_version(self):
        """Retrieve the latest public listed version of an addon.

        If the add-on is not public, it can return a listed version awaiting
        review (since non-public add-ons should not have public versions)."""
        return (
            self.versions.filter(
                channel=amo.CHANNEL_LISTED,
                file__status__in=self.valid_file_statuses,
            )
            .order_by('created')
            .last()
        )

    def find_latest_version(
        self, channel, exclude=((amo.STATUS_DISABLED,)), deleted=False
    ):
        """Retrieve the latest version of an add-on for the specified channel.

        If channel is None either channel is returned.

        Keyword arguments:
        exclude -- exclude versions for which all files have one of those statuses
                   (default STATUS_DISABLED).  `exclude=()` to include all statuses.
        deleted -- include deleted addons and versions. You probably want `exclude=()`
                   too as files are typically set to STATUS_DISABLED on delete."""

        # If the add-on hasn't been saved yet, it should not have a latest version.
        # Nor if it's deleted, unless specified.
        if not self.id or (self.status == amo.STATUS_DELETED and not deleted):
            return None

        # Avoid most transformers - keep translations because they don't
        # get automatically fetched if you just access the field without
        # having made the query beforehand, and we don't know what callers
        # will want ; but for the rest of them, since it's a single
        # instance there is no reason to call the default transformers.
        manager = 'objects' if not deleted else 'unfiltered_for_relations'
        return (
            self.versions(manager=manager)
            .exclude(file__status__in=exclude)
            .filter(
                **{'channel': channel} if channel is not None else {},
                file__isnull=False,
            )
            .only_translations()
            .order_by('created')
            .last()
        )

    @use_primary_db
    def update_version(self, ignore=None, _signal=True):
        """
        Update the current_version field on this add-on if necessary.

        Returns True if we updated the current_version field.

        The optional ``ignore`` parameter, if present, is a a version
        to not consider as part of the update, since it may be in the
        process of being deleted.

        Pass ``_signal=False`` if you want to no signals fired at all.

        """
        new_current_version = self.find_latest_public_listed_version()
        updated = {}
        send_signal = False
        if self._current_version != new_current_version:
            updated['_current_version'] = new_current_version
            send_signal = True

        # update_version can be called by a post_delete signal (such
        # as File's) when deleting a version. If so, we should avoid putting
        # that version-being-deleted in any fields.
        if ignore is not None:
            updated = {k: v for k, v in updated.items() if v != ignore}

        if updated:
            diff = [self._current_version, new_current_version]
            # Pass along _signal to the .update() to prevent it from firing
            # signals if we don't want them.
            updated['_signal'] = _signal
            try:
                self.update(**updated)
                if send_signal and _signal:
                    signals.version_changed.send(sender=self.__class__, instance=self)
                log.info(
                    'Version changed from current: %s to %s '
                    'for addon %s' % tuple(diff + [self])
                )
            except Exception as e:
                log.error(
                    'Could not save version changes current: %s to %s '
                    'for addon %s (%s)' % tuple(diff + [self, e])
                )

        return bool(updated)

    def increment_theme_version_number(self):
        """Increment theme version number by 1."""
        latest_version = self.find_latest_version(None)
        version = latest_version or self.current_version
        version.version = str(float(version.version) + 1)
        # Set the current version.
        self.update(_current_version=version.save())

    @property
    def current_version(self):
        """Return the latest public listed version of an addon.

        If the add-on is not public, it can return a listed version awaiting
        review (since non-public add-ons should not have public versions).

        If the add-on has not been created yet or is deleted, it returns None.
        """
        if not self.id or self.status == amo.STATUS_DELETED:
            return None
        try:
            return self._current_version
        except ObjectDoesNotExist:
            pass
        return None

    @cached_property
    def latest_unlisted_version(self):
        """Shortcut property for Addon.find_latest_version(
        channel=CHANNEL_UNLISTED)."""
        return self.find_latest_version(channel=amo.CHANNEL_UNLISTED)

    def get_icon_dir(self):
        return os.path.join(
            settings.MEDIA_ROOT, 'addon_icons', '%s' % (self.id // 1000)
        )

    def get_icon_path(self, size):
        return os.path.join(
            self.get_icon_dir(), f'{self.pk}-{size}.{amo.ADDON_ICON_FORMAT}'
        )

    def get_icon_url(self, size):
        """
        Returns the addon's icon url according to icon_type.

        If it's a theme and there is no icon set, it will return the default
        theme icon.

        If it's something else, it will return the default add-on icon.
        """
        # Get the closest allowed size without going over
        if size not in amo.ADDON_ICON_SIZES and size >= amo.ADDON_ICON_SIZES[0]:
            size = [s for s in amo.ADDON_ICON_SIZES if s < size][-1]
        elif size < amo.ADDON_ICON_SIZES[0]:
            size = amo.ADDON_ICON_SIZES[0]

        # Figure out what to return for an image URL
        if not self.icon_type:
            return self.get_default_icon_url(size)
        else:
            # Use the icon hash if we have one as the cachebusting suffix,
            # otherwise fall back to the add-on modification date.
            suffix = self.icon_hash or str(int(time.mktime(self.modified.timetuple())))
            path = '/'.join(
                [
                    # Path is the filesystem path, so it matches get_icon_dir()
                    # and get_icon_path().
                    'addon_icons',
                    f'{self.id // 1000}',
                    f'{self.id}-{size}.{amo.ADDON_ICON_FORMAT}?modified={suffix}',
                ]
            )
            return f'{settings.MEDIA_URL}{path}'

    def get_default_icon_url(self, size):
        return staticfiles_storage.url(f'img/addon-icons/default-{size}.png')

    @use_primary_db
    def update_status(self, ignore_version=None):
        self.reload()

        # We don't auto-update the status of deleted or force disabled add-ons.
        if self.status in (amo.STATUS_DELETED, amo.STATUS_DISABLED):
            self.update_version(ignore=ignore_version)
            return

        listed_versions = self.versions.filter(channel=amo.CHANNEL_LISTED)
        correct_status = self.status
        force_update = False
        if AddonApprovalsCounter.objects.filter(
            addon=self,
            content_review_status__in=AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REJECTED,
        ).exists():
            # If the content review failed, the status should stay as rejected
            correct_status = amo.STATUS_REJECTED
            reason = 'content review failed'
        elif listed_versions.filter(file__status=amo.STATUS_APPROVED).exists():
            correct_status = amo.STATUS_APPROVED
            reason = 'unapproved add-on with approved listed version'

            if (
                self.status == amo.STATUS_APPROVED
                and self.find_latest_version(channel=amo.CHANNEL_LISTED).file.status
                == amo.STATUS_AWAITING_REVIEW
            ):
                # Addon is public, but its latest file is not (it's the case on
                # a new file upload). So, force the update, to trigger watch_status,
                # which takes care of setting due date for the review when needed.
                force_update = True
                reason = 'triggering watch_status'

        elif listed_versions.filter(file__status=amo.STATUS_AWAITING_REVIEW).exists():
            if self.status != amo.STATUS_NULL or self.has_complete_metadata():
                correct_status = amo.STATUS_NOMINATED
                reason = 'complete metadata and/or listed version awaiting review'
        else:
            correct_status = amo.STATUS_NULL
            reason = 'no listed versions that are approved or awaiting review'

        if correct_status != self.status or force_update:
            log.info(
                'Changing add-on status [%s]: %s => %s (%s).'
                % (self.id, self.status, correct_status, reason)
            )
            self.update(status=correct_status)
            # If task_user doesn't exist that's no big issue (i.e. in tests)
            try:
                task_user = get_task_user()
            except UserProfile.DoesNotExist:
                task_user = None
            activity.log_create(
                amo.LOG.CHANGE_STATUS, self, self.status, user=task_user
            )

        self.update_version(ignore=ignore_version)

    @staticmethod
    def attach_related_versions(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = {addon.id: addon for addon in addons}

        all_ids = set(filter(None, (addon._current_version_id for addon in addons)))
        versions = list(Version.objects.filter(id__in=all_ids).order_by())
        for version in versions:
            try:
                addon = addon_dict[version.addon_id]
            except KeyError:
                log.info('Version %s has an invalid add-on id.' % version.id)
                continue
            if addon._current_version_id == version.id:
                addon._current_version = version

            version.addon = addon

    @staticmethod
    def _attach_authors(
        addons,
        addon_dict=None,
        manager='objects',
        listed=True,
        to_attr='listed_authors',
    ):
        # It'd be nice if this could be done with something like
        # qs.prefetch_related(
        #     Prefetch('authors', queryset=UserProfile.objects.annotate(
        #         role=F('addonuser__role'), listed=F('addonuser__listed'))))
        # instead, but that doesn't work because the prefetch queryset is
        # making a different join for addonuser than the one used by the
        # manytomanyfield, so the results are completely wrong when there are
        # more than one add-on. Also this wouldn't let us customize the
        # AddonUser manager to include/exclude deleted roles.
        # So instead, we do it via AddonUser, copy the properties on the users
        # and throw away the AddonUser instances afterwards.
        if addon_dict is None:
            addon_dict = {addon.id: addon for addon in addons}

        filters = {'addon__in': addons}
        if listed is not None:
            filters['listed'] = listed
        addonuser_qs = getattr(AddonUser, manager).all()
        addonuser_qs = (
            addonuser_qs.filter(**filters)
            .order_by('addon_id', 'position')
            .select_related('user')
        )
        seen = set()
        groupby = itertools.groupby(addonuser_qs, key=lambda u: u.addon_id)
        for addon_id, addonusers in groupby:
            authors = []
            for addonuser in addonusers:
                addonuser.user.role = addonuser.role
                addonuser.user.listed = addonuser.listed
                authors.append(addonuser.user)
            setattr(addon_dict[addon_id], to_attr, authors)
            seen.add(addon_id)
        # set authors to empty list on addons without any.
        [
            setattr(addon, to_attr, [])
            for addon in addon_dict.values()
            if addon.id not in seen
        ]

    @staticmethod
    def attach_listed_authors(addons, addon_dict=None):
        Addon._attach_authors(addons, addon_dict=addon_dict)

    @staticmethod
    def attach_all_authors(addons, addon_dict=None):
        Addon._attach_authors(
            addons,
            addon_dict=addon_dict,
            manager='unfiltered',
            listed=None,
            to_attr='all_authors',
        )

    @staticmethod
    def attach_previews(addons, addon_dict=None, no_transforms=False):
        if addon_dict is None:
            addon_dict = {a.id: a for a in addons}

        qs = Preview.objects.filter(addon__in=addons, position__gte=0).order_by()
        if no_transforms:
            qs = qs.no_transforms()
        qs = sorted(qs, key=lambda x: (x.addon_id, x.position, x.created))
        # Pre-fill all the addon instances with an empty list
        # We set an inner `._current_preview` because we don't know if the addon is a
        # theme at this point - and can't check addon.type without triggering a query.
        for addon in addon_dict.values():
            addon._current_previews = []
        for addon_id, previews in itertools.groupby(qs, lambda x: x.addon_id):
            addon = addon_dict[addon_id]
            addon._current_previews = list(previews)

    @staticmethod
    def attach_static_categories(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = {addon.id: addon for addon in addons}

        qs = AddonCategory.objects.filter(addon__in=addon_dict.values()).values_list(
            'addon_id', 'category_id'
        )
        for addon_id in addon_dict:
            addon_dict[addon_id].all_categories = []

        for addon_id, cats_iter in itertools.groupby(qs, key=lambda x: x[0]):
            # The second value of each tuple in cats_iter are the category ids
            # we want.
            addon_dict[addon_id].category_ids = sorted(c[1] for c in cats_iter)
            addon_dict[addon_id].all_categories = [
                CATEGORIES_BY_ID[cat_id]
                for cat_id in addon_dict[addon_id].category_ids
                if cat_id in CATEGORIES_BY_ID
            ]

    @staticmethod
    def transformer(addons):
        if not addons:
            return

        addon_dict = {a.id: a for a in addons}

        # Attach categories.
        Addon.attach_static_categories(addons, addon_dict=addon_dict)
        # Set _current_version and attach listed authors.
        Addon.attach_related_versions(addons, addon_dict=addon_dict)
        Addon.attach_listed_authors(addons, addon_dict=addon_dict)
        # Attach previews.
        Addon.attach_previews(addons, addon_dict=addon_dict)

        return addon_dict

    @property
    def contribution_url(self, lang=settings.LANGUAGE_CODE, app=settings.DEFAULT_APP):
        return reverse('addons.contribute', args=[self.slug])

    def can_request_review(self):
        """Return whether an add-on can request a review or not."""
        if self.is_disabled or self.status in (
            amo.STATUS_APPROVED,
            amo.STATUS_NOMINATED,
            amo.STATUS_DELETED,
        ):
            return False

        latest_version = self.find_latest_version(amo.CHANNEL_LISTED, exclude=())

        return (
            latest_version is not None
            and not latest_version.file.approval_date
            and not latest_version.human_review_date
        )

    @property
    def is_disabled(self):
        """True if this Addon is disabled.

        It could be disabled by an admin or disabled by the developer
        """
        return self.status == amo.STATUS_DISABLED or self.disabled_by_user

    @property
    def is_deleted(self):
        return self.status == amo.STATUS_DELETED

    def is_unreviewed(self):
        return self.status in (amo.STATUS_NOMINATED, amo.STATUS_REJECTED)

    def is_public(self):
        return self.status == amo.STATUS_APPROVED and not self.disabled_by_user

    def can_submit_listed_versions(self):
        return (
            not self.is_disabled
            and not self.is_deleted
            and self.status != amo.STATUS_REJECTED
        )

    def has_complete_metadata(self, has_listed_versions=None):
        """See get_required_metadata for has_listed_versions details."""
        return all(self.get_required_metadata(has_listed_versions=has_listed_versions))

    def get_required_metadata(self, has_listed_versions=None):
        """If has_listed_versions is not specified this method will return the
        current (required) metadata (truthy values if present) for this Addon.

        If has_listed_versions is specified then the method will act as if
        Addon.has_listed_versions() returns that value. Used to predict if the
        addon will require extra metadata before a version is created."""
        if has_listed_versions is None:
            has_listed_versions = self.has_listed_versions()
        if not has_listed_versions:
            # Add-ons with only unlisted versions have no required metadata.
            return []
        # We need to find out if the add-on has a license set. We prefer to
        # check the current_version first because that's what would be used for
        # public pages, but if there isn't any listed version will do.
        version = self.current_version or self.find_latest_version(
            channel=amo.CHANNEL_LISTED, exclude=()
        )
        return [
            self.all_categories,
            self.name,
            self.summary,
            (version and version.license_id),
        ]

    def should_redirect_to_submit_flow(self):
        return (
            self.status == amo.STATUS_NULL
            and not self.has_complete_metadata()
            and self.find_latest_version(channel=amo.CHANNEL_LISTED)
        )

    def can_be_deleted(self):
        return not self.is_deleted

    def has_listed_versions(self, include_deleted=False):
        if include_deleted:
            manager = self.versions(manager='unfiltered_for_relations')
        else:
            manager = self.versions
        return (
            self._current_version_id
            or manager.filter(channel=amo.CHANNEL_LISTED).exists()
        )

    def has_unlisted_versions(self, include_deleted=False):
        if include_deleted:
            manager = self.versions(manager='unfiltered_for_relations')
        else:
            manager = self.versions
        return manager.filter(channel=amo.CHANNEL_UNLISTED).exists()

    def _is_recommended_theme(self):
        from olympia.bandwagon.models import CollectionAddon

        return (
            self.type == amo.ADDON_STATICTHEME
            and CollectionAddon.objects.filter(
                collection_id=settings.COLLECTION_FEATURED_THEMES_ID, addon=self
            ).exists()
        )

    def promoted_groups(self, *, currently_approved=True):
        """Is the addon currently promoted for the current applications?

        Returns a queryset of PromotedGroups.

        `currently_approved=True` means only returns True if
        self.current_version is approved for the current promotion & apps.
        If currently_approved=False then promotions where there isn't approval
        are returned too.
        """
        from olympia.promoted.models import PromotedGroup

        return (
            PromotedGroup.objects.approved_for(addon=self)
            if currently_approved
            else PromotedGroup.objects.all_for(addon=self)
        )

    @cached_property
    def publicly_promoted_groups(self):
        promoted_group = self.promoted_groups()
        if promoted_group:
            return promoted_group.filter(is_public=True).all()
        else:
            if self._is_recommended_theme():
                from olympia.promoted.models import PromotedGroup

                return [
                    PromotedGroup.objects.get(
                        group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
                    )
                ]
        return []

    @cached_property
    def is_promoted(self):
        return bool(self.promoted_groups(currently_approved=False))

    @property
    def all_applications(self):
        return self.all_applications_for()

    def all_applications_for(self, promoted_group=None):
        from olympia.addons.serializers import APP_IDS
        from olympia.constants.applications import APP_USAGE

        qs = self.promotedaddon
        if promoted_group:
            qs = qs.filter(promoted_group=promoted_group)
        apps = qs.values_list('application_id', flat=True)

        return (
            [APP_IDS.get(app_id) for app_id in apps]
            if apps
            else [app for app in APP_USAGE]
        )

    @property
    def approved_applications(self):
        """All the applications that the current addon is approved for,
        for the current version."""
        return self.approved_applications_for()

    def approved_applications_for(self, promoted_group=None):
        """The applications that the given promoted group is approved for,
        for the current version."""
        from olympia.addons.serializers import APP_IDS

        if self._is_recommended_theme():
            return self.all_applications if self.current_version else []

        return [
            APP_IDS.get(app_id)
            for app_id in self.approved_promotions(
                promoted_group=promoted_group
            ).values_list('application_id', flat=True)
        ]

    def approved_promotions(self, promoted_group=None):
        """Returns PromotedAddons with an associated
        approval (PromotedApproval) for a specified promoted group,
        or all groups if none is given.
        """
        from olympia.promoted.models import PromotedAddon, PromotedApproval

        # An addon is approved for a promoted group if:
        # 1. For each PromotedAddon A, there exists a
        #    PromotedApproval B such that
        #       i. Are the same group,
        #       ii. Are the same application,
        #       iii. A.addon.current_version = B.version, OR
        # 2. is a promoted group that does not require prereview.

        approved_promotions = PromotedAddon.objects.filter(
            Q(
                models.Exists(
                    PromotedApproval.objects.filter(
                        promoted_group=models.OuterRef('promoted_group'),
                        application_id=models.OuterRef('application_id'),
                        version=models.OuterRef('addon___current_version'),
                    )
                )
                | Q(
                    promoted_group__listed_pre_review=False,
                    promoted_group__unlisted_pre_review=False,
                )
            ),
            addon=self,
        )

        if promoted_group:
            approved_promotions = approved_promotions.filter(
                promoted_group=promoted_group
            )

        return approved_promotions

    def approve_for_version(self, version=None, promoted_groups=None):
        """Create PromotedApproval for current applications in the given
        promoted groups. If none are given, approve all promotions."""
        version = version or self.current_version
        promotions = self.promotedaddon
        if promoted_groups:
            promotions = promotions.filter(promoted_group__in=promoted_groups)

        for promotion in promotions.all():
            promotion.approve_for_version(version)

    @cached_property
    def compatible_apps(self):
        """Shortcut to get compatible apps for the current version."""
        if self.current_version:
            return self.current_version.compatible_apps
        else:
            return {}

    @classmethod
    def type_can_set_compatibility(cls, addon_type):
        """True if this add-on type allows compatiblity changes."""
        return addon_type not in amo.NO_COMPAT_CHANGES

    @property
    def can_set_compatibility(self):
        return self.type_can_set_compatibility(self.type)

    @property
    def can_be_compatible_with_all_fenix_versions(self):
        """Whether or not the addon is allowed to be compatible with all Fenix
        versions (i.e. it's a recommended/line extension for Android)."""
        promotions = self.publicly_promoted_groups
        approved_applications = self.approved_applications

        return (
            promotions
            and all(
                promotion.can_be_compatible_with_all_fenix_versions
                for promotion in promotions
            )
            and amo.ANDROID in approved_applications
        )

    def has_author(self, user):
        """True if ``user`` is an author of the add-on."""
        if user is None or user.is_anonymous:
            return False
        return AddonUser.objects.filter(addon=self, user=user).exists()

    @classmethod
    def _last_updated_queries(cls):
        """
        Get the queries used to calculate addon.last_updated.
        """
        status_change = Max('versions__file__datestatuschanged')
        public = (
            Addon.objects.filter(
                status=amo.STATUS_APPROVED, versions__file__status=amo.STATUS_APPROVED
            )
            .values('id')
            .annotate(last_updated=status_change)
        )

        stati = amo.VALID_ADDON_STATUSES
        exp = (
            Addon.objects.exclude(status__in=stati)
            .filter(versions__file__status__in=amo.VALID_FILE_STATUSES)
            .values('id')
            .annotate(last_updated=Max('versions__file__created'))
        )

        return {'public': public, 'exp': exp}

    @cached_property
    def all_categories(self):
        self.attach_static_categories([self], {self.id: self})
        return self.all_categories

    def set_categories(self, categories):
        # Add new categories.
        for category in set(categories) - set(self.all_categories):
            AddonCategory.objects.create(addon=self, category=category)

        # Remove old categories.
        for category in set(self.all_categories) - set(categories):
            AddonCategory.objects.filter(addon=self, category_id=category.id).delete()

        # Update categories cache on the model.
        self.all_categories = categories

        # Make sure the add-on is properly re-indexed
        update_search_index(Addon, self)

    @property
    def current_previews(self):
        """Previews for the current version, or all of them if not a
        static theme."""
        if self.has_per_version_previews:
            if not hasattr(self, '_current_version_previews'):
                self._current_version_previews = (
                    list(self.current_version.previews.all())
                    if self.current_version
                    else []
                )
            return self._current_version_previews
        else:
            if not hasattr(self, '_current_previews'):
                self._current_previews = list(self.previews.all())
            return self._current_previews

    @current_previews.setter
    def current_previews(self, value):
        if self.has_per_version_previews:
            self._current_version_previews = value
        else:
            self._current_previews = value

    @current_previews.deleter
    def current_previews(self):
        if hasattr(self, '_current_version_previews'):
            del self._current_version_previews
        if hasattr(self, '_current_previews'):
            del self._current_previews

    @property
    def has_per_version_previews(self):
        return self.type == amo.ADDON_STATICTHEME

    def remove_locale(self, locale):
        """NULLify strings in this locale for the add-on and versions."""
        for o in itertools.chain([self], self.versions.all()):
            Translation.objects.remove_for(o, locale)

    # Aliases for reviewerflags below are not just useful in case
    # AddonReviewerFlags does not exist for this add-on: they are also used
    # by reviewer tools get_flags() function to return flags shown to reviewers
    # in both the review queues and the review page.
    @property
    def needs_admin_theme_review(self):
        try:
            return self.reviewerflags.needs_admin_theme_review
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_disabled(self):
        try:
            return self.reviewerflags.auto_approval_disabled
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_disabled_unlisted(self):
        try:
            return self.reviewerflags.auto_approval_disabled_unlisted
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_disabled_until_next_approval(self):
        try:
            return self.reviewerflags.auto_approval_disabled_until_next_approval
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_disabled_until_next_approval_unlisted(self):
        try:
            return (
                self.reviewerflags.auto_approval_disabled_until_next_approval_unlisted
            )
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_delayed_until(self):
        try:
            return self.reviewerflags.auto_approval_delayed_until
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_delayed_until_unlisted(self):
        try:
            return self.reviewerflags.auto_approval_delayed_until_unlisted
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_delayed_indefinitely(self):
        return self.auto_approval_delayed_until == datetime.max

    @property
    def auto_approval_delayed_temporarily(self):
        return (
            bool(self.auto_approval_delayed_until)
            and self.auto_approval_delayed_until != datetime.max
            and self.auto_approval_delayed_until > datetime.now()
        )

    @property
    def auto_approval_delayed_indefinitely_unlisted(self):
        return self.auto_approval_delayed_until_unlisted == datetime.max

    @property
    def auto_approval_delayed_temporarily_unlisted(self):
        return (
            bool(self.auto_approval_delayed_until_unlisted)
            and self.auto_approval_delayed_until_unlisted != datetime.max
        )

    def set_auto_approval_delay_if_higher_than_existing(
        self, delay, unlisted_only=False
    ):
        """
        Set auto_approval_delayed_until/auto_approval_delayed_until_unlisted on
        the add-on to a new value if the new value is further in the future
        than the existing one.
        """
        # There are 4 cases to handle:
        # - flag object is non-existent
        # - flag object exists, but current delay is NULL
        # - flag object exists, but current delay is higher than new one
        # - flag object exists, but current delay is lower than new one
        # Django doesn't support F()/Coalesce() in update_or_create() calls
        # (https://code.djangoproject.com/ticket/25195) so we have to create
        # the flag first if it doesn't exist. On top of that, with MySQL,
        # Greatest() returns NULL if either value is NULL, so we need to
        # Coalesce the existing value to avoid that.
        defaults = {
            'auto_approval_delayed_until_unlisted': delay,
        }
        update_defaults = {
            'auto_approval_delayed_until_unlisted': Greatest(
                Coalesce('auto_approval_delayed_until_unlisted', delay),
                delay,
            ),
        }
        if not unlisted_only:
            defaults['auto_approval_delayed_until'] = delay
            update_defaults['auto_approval_delayed_until'] = Greatest(
                Coalesce('auto_approval_delayed_until', delay),
                delay,
            )
        AddonReviewerFlags.objects.get_or_create(addon=self, defaults=defaults)
        AddonReviewerFlags.objects.filter(addon=self).update(**update_defaults)
        # Make sure the cached related field is up to date.
        self.reviewerflags.reload()

    @classmethod
    def get_lookup_field(cls, identifier):
        lookup_field = 'pk'
        if identifier and not str(identifier).isdigit():
            # If the identifier contains anything other than a digit, it's
            # either a slug or a guid. guids need to contain either {} or @,
            # which are invalid in a slug.
            if amo.ADDON_GUID_PATTERN.match(identifier):
                lookup_field = 'guid'
            else:
                lookup_field = 'slug'
        return lookup_field

    @property
    def addonguid_guid(self):
        """Use this function to avoid having to wrap `addon.addonguid.guid` in
        a try...except.
        There *should* be a matching AddonGUID record for every Addon with a
        guid, but the foreign key is from AddonGUID to Addon so there's a
        possiblity of bad data leading to the AddonGUID not existing.  Plus we
        don't want this to fail if an upload with guid=None somehow ended up
        getting through.
        """
        return getattr(self, 'addonguid', self).guid

    @cached_property
    def block(self):
        from olympia.blocklist.models import Block

        # Block.guid is unique so it's either on the list or not.
        return Block.objects.filter(guid=self.addonguid_guid).last()

    @property
    def blocklistsubmissions(self):
        from olympia.blocklist.models import BlocklistSubmission

        return BlocklistSubmission.get_submissions_from_guid(self.addonguid_guid)

    @cached_property
    def tag_list(self):
        attach_tags([self])
        return self.tag_list

    def set_tag_list(self, new_tag_list):
        tag_list_to_add = set(new_tag_list) - set(self.tag_list)
        tag_list_to_drop = set(self.tag_list) - set(new_tag_list)
        tags = Tag.objects.filter(tag_text__in=(*tag_list_to_add, *tag_list_to_drop))

        for tag in tags:
            if tag.tag_text in tag_list_to_add:
                tag.add_tag(self)
            elif tag.tag_text in tag_list_to_drop:
                tag.remove_tag(self)
        self.tag_list = new_tag_list

    def update_all_due_dates(self):
        """
        Update all due dates on versions of this add-on.

        Use when dealing with having to re-check all due dates for all versions
        of an add-on as it does it in a slightly more optimized than checking
        for each version individually.
        """
        manager = self.versions(manager='unfiltered_for_relations')
        for version in (
            manager.should_have_due_date().filter(due_date__isnull=True).no_transforms()
        ):
            due_date = get_review_due_date()
            version.reset_due_date(due_date=due_date, should_have_due_date=True)
        for version in (
            manager.should_have_due_date(negate=True)
            .filter(due_date__isnull=False)
            .no_transforms()
        ):
            version.reset_due_date(should_have_due_date=False)

    def rollbackable_versions_qs(self, channel):
        # Needs to be an extension
        if not self.type == amo.ADDON_EXTENSION or not waffle.switch_is_active(
            'version-rollback'
        ):
            return Version.objects.none()
        qs = self.versions.filter(channel=channel, file__status=amo.STATUS_APPROVED)
        # You can't rollback to the latest approved version
        qs = qs.exclude(id=qs.values('id')[:1])
        return qs.order_by('-created')

    def get_usage_tier(self):
        """Return the UsageTier instance the add-on is a part of, or None.

        Note that UsageTier has additional filtering on top of just usage, so
        it's possible for some add-ons to not be part of any UsageTier even if
        their average_daily_users value would match one."""
        from olympia.reviewers.models import UsageTier

        for tier in UsageTier.objects.all():
            if tier.get_addons().filter(pk=self.pk).exists():
                return tier
        return None

    @property
    def is_listing_noindexed(self):
        try:
            noindex_until = self.addonlistinginfo.noindex_until
        except Addon.addonlistinginfo.RelatedObjectDoesNotExist:
            noindex_until = None
        return noindex_until > datetime.now() if noindex_until else False


dbsignals.pre_save.connect(save_signal, sender=Addon, dispatch_uid='addon_translations')


@receiver(signals.version_changed, dispatch_uid='version_changed')
def version_changed(sender, instance, **kw):
    from . import tasks

    tasks.version_changed.delay(instance.pk)


@receiver(dbsignals.post_save, sender=Addon, dispatch_uid='addons.search.index')
def update_search_index(sender, instance, **kw):
    from . import tasks

    if not kw.get('raw'):
        tasks.index_addons.delay([instance.id])


@Addon.on_change
def watch_status(old_attr=None, new_attr=None, instance=None, sender=None, **kwargs):
    """
    Watch add-on status changes and react accordingly, updating author profile
    visibility, disabling versions when disabled_by_user is set, and setting
    due date on versions if the addon is new in queue or updating.

    The due date cannot be reset, say, when a developer cancels their request
    for review and re-requests review.

    If a version is rejected after nomination, the developer has to upload a
    new version.
    """
    new_status = new_attr.get('status') if new_attr else None
    old_status = old_attr.get('status') if old_attr else None
    disabled_by_user = new_attr.get('disabled_by_user') if new_attr else None

    # Update the author's account profile visibility
    if new_status != old_status:
        [author.update_has_full_profile() for author in instance.authors.all()]

    if new_status not in amo.VALID_ADDON_STATUSES or not (
        latest_version := instance.find_latest_version(channel=amo.CHANNEL_LISTED)
    ):
        return
    if disabled_by_user and latest_version.file.status == amo.STATUS_AWAITING_REVIEW:
        # If a developer disables their add-on, the listed version waiting for
        # review should be disabled right away, we don't want reviewers to look
        # at it. That might in turn change the add-on status from NOMINATED
        # back to NULL, through update_status().
        latest_version.file.update(
            status=amo.STATUS_DISABLED,
            original_status=latest_version.file.status,
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
        )
        instance.update_status()
    elif old_status == amo.STATUS_NOMINATED:
        # Update latest version due date if necessary for nominated add-ons.
        inherit_due_date_if_nominated(None, latest_version)
    else:
        # New: will (re)set due date only if it's None.
        latest_version.reset_due_date()


@receiver(
    models.signals.post_delete,
    sender=Addon,
    dispatch_uid='addon-delete',
)
def update_due_date_for_addon_delete(sender, instance, **kw):
    instance.update_all_due_dates()


def attach_translations_dict(addons):
    """Put all translations into a translations dict."""
    attach_trans_dict(Addon, addons)


def attach_tags(addons):
    addon_dict = {addon.id: addon for addon in addons}
    for addon in addons:
        addon.tag_list = []  # make sure all the addons have the property set
    qs = Tag.objects.filter(addons__in=addon_dict).values_list('addons__id', 'tag_text')
    for addon, tags in sorted_groupby(qs, lambda x: x[0]):
        addon_dict[addon].tag_list = [t[1] for t in tags]


class AddonReviewerFlags(ModelBase):
    addon = models.OneToOneField(
        Addon, primary_key=True, on_delete=models.CASCADE, related_name='reviewerflags'
    )
    needs_admin_code_review = models.BooleanField(default=False, null=True)
    needs_admin_content_review = models.BooleanField(default=False, null=True)
    needs_admin_theme_review = models.BooleanField(default=False)
    auto_approval_disabled = models.BooleanField(default=False)
    auto_approval_disabled_unlisted = models.BooleanField(default=None, null=True)
    auto_approval_disabled_until_next_approval = models.BooleanField(
        default=None, null=True
    )
    auto_approval_disabled_until_next_approval_unlisted = models.BooleanField(
        default=None, null=True
    )
    auto_approval_delayed_until = models.DateTimeField(
        blank=True, default=None, null=True
    )
    auto_approval_delayed_until_unlisted = models.DateTimeField(
        blank=True, default=None, null=True
    )
    notified_about_expiring_delayed_rejections = models.BooleanField(
        default=None, null=True
    )


class AddonRegionalRestrictions(ModelBase):
    addon = models.OneToOneField(
        Addon,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name='regional_restrictions',
        help_text='Add-on id this item will point to.',
    )
    excluded_regions = models.JSONField(
        default=list,
        help_text='JSON style list of ISO 3166-1 alpha-2 country (region) '
        'codes. Codes will be uppercased. E.g. `["CN"]`',
    )

    class Meta:
        verbose_name_plural = 'Addon Regional Restrictions'

    def __str__(self):
        return '%s: %d' % (self.addon, len(self.excluded_regions))

    def clean(self):
        super().clean()
        self.excluded_regions = [str(item).upper() for item in self.excluded_regions]


class MigratedLWT(OnChangeMixin, ModelBase):
    lightweight_theme_id = models.PositiveIntegerField()
    getpersonas_id = models.PositiveIntegerField()
    static_theme = models.ForeignKey(
        Addon, unique=True, related_name='migrated_from_lwt', on_delete=models.CASCADE
    )

    class Meta:
        db_table = 'migrated_personas'
        indexes = [
            LongNameIndex(
                fields=('static_theme',),
                name='migrated_personas_static_theme_id_fk_addons_id',
            ),
            LongNameIndex(
                fields=('getpersonas_id',), name='migrated_personas_getpersonas_id'
            ),
        ]


class AddonCategory(models.Model):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    category_id = models.PositiveIntegerField()

    class Meta:
        db_table = 'addons_categories'
        indexes = [
            models.Index(fields=('category_id', 'addon'), name='category_addon_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('addon', 'category_id'),
                name='addons_categories_addon_category_id',
            ),
        ]

    def __init__(self, *args, **kwargs):
        if 'category' in kwargs:
            kwargs['category_id'] = kwargs.pop('category').id
        super().__init__(*args, **kwargs)

    @property
    def category(self):
        return CATEGORIES_BY_ID.get(self.category_id)


class AddonUserQuerySet(models.QuerySet):
    def delete(self):
        return self.update(original_role=F('role'), role=amo.AUTHOR_ROLE_DELETED)

    def undelete(self):
        default_original_role = self.model._meta.get_field('original_role').default
        return self.update(
            role=models.F('original_role'), original_role=default_original_role
        )


class AddonUserManager(ManagerBase):
    _queryset_class = AddonUserQuerySet

    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        super().__init__()
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.include_deleted:
            qs = qs.exclude(role=amo.AUTHOR_ROLE_DELETED)
        return qs


class UnfilteredAddonUserManagerForRelations(AddonUserManager):
    """Like AddonUserManager, but defaults to include deleted objects.

    Designed to be used in reverse relations of AddonUser that want to include
    soft-deleted objects.
    """

    def __init__(self, include_deleted=True):
        super().__init__(include_deleted=include_deleted)


class AddonUser(OnChangeMixin, SaveUpdateMixin, models.Model):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    role = models.SmallIntegerField(
        default=amo.AUTHOR_ROLE_OWNER, choices=amo.AUTHOR_CHOICES_UNFILTERED
    )
    original_role = models.SmallIntegerField(
        default=amo.AUTHOR_ROLE_DEV,
        choices=amo.AUTHOR_CHOICES,
        editable=False,
        help_text='Role to assign if user is unbanned',
    )
    listed = models.BooleanField(_('Listed'), default=True)
    position = models.IntegerField(default=0)

    unfiltered = AddonUserManager(include_deleted=True)
    objects = AddonUserManager()
    unfiltered_for_relations = UnfilteredAddonUserManagerForRelations()

    class Meta:
        # see Addon.Meta for details of why this base_manager_name is important
        base_manager_name = 'unfiltered'
        db_table = 'addons_users'
        indexes = [
            models.Index(fields=('listed',), name='addons_users_listed_idx'),
            LongNameIndex(
                fields=('addon', 'user', 'listed'),
                name='addons_users_addon_user_listed_idx',
            ),
            models.Index(
                fields=('addon', 'listed'), name='addons_users_addon_listed_idx'
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('addon', 'user'), name='addons_users_addon_user'
            ),
        ]

    def delete(self):
        # soft-delete
        self.update(original_role=self.role, role=amo.AUTHOR_ROLE_DELETED)

    @property
    def is_deleted(self):
        return self.role == amo.AUTHOR_ROLE_DELETED


@AddonUser.on_change
def watch_addon_user(
    old_attr=None, new_attr=None, instance=None, sender=None, **kwargs
):
    # For any new authors added after the first one, we want to re-run the
    # narc scanner to take that author into account (no need to do it for the
    # first one, the scan would happen anyway after creating the version when
    # auto-approval is attempted, and doing it here might be too early).
    addon = instance.addon
    is_new_author_besides_first_one = (
        # We're adding an author
        instance.pk
        and old_attr
        and old_attr.get('id') is None
        # There was at least one other author before (i.e. this is the second
        # or more author)
        and addon.addonuser_set.all().exclude(pk=instance.pk).exists()
    )
    if (
        waffle.switch_is_active('enable-narc')
        and is_new_author_besides_first_one
        and (version := addon.find_latest_non_rejected_listed_version())
    ):
        from olympia.scanners.tasks import run_narc_on_version

        run_narc_on_version.delay(version.pk)
    instance.user.update_has_full_profile()
    # Update ES because authors is included.
    update_search_index(sender=sender, instance=addon, **kwargs)


models.signals.post_delete.connect(
    watch_addon_user, sender=AddonUser, dispatch_uid='delete_addon_user'
)


class AddonUserPendingConfirmation(OnChangeMixin, SaveUpdateMixin, models.Model):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    user = user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    role = models.SmallIntegerField(
        default=amo.AUTHOR_ROLE_OWNER, choices=amo.AUTHOR_CHOICES
    )
    listed = models.BooleanField(_('Listed'), default=True)
    # Note: we don't bother with position for authors waiting confirmation,
    # because it's impossible to properly reconcile it with the confirmed
    # authors. Instead, authors waiting confirmation are displayed in the order
    # they have been added, and when they are confirmed they end up in the
    # last position by default.

    class Meta:
        db_table = 'addons_users_pending_confirmation'
        constraints = [
            models.UniqueConstraint(
                fields=('addon', 'user'),
                name='addons_users_pending_confirmation_addon_id_user_id_38e3bb32_uniq',
            ),
        ]


class AddonApprovalsCounter(ModelBase):
    """Model holding a counter of the number of times a listed version
    belonging to an add-on has been approved by a human. Reset everytime a
    listed version is auto-approved for this add-on.

    Holds additional fields:
    - last_human_review, the date of the last time a human fully reviewed the
      add-on
    - last_content_review, the date of the last time a human fully reviewed the
      add-on content (not code).
    - content_review_status, the status of the last content review.
    """

    class CONTENT_REVIEW_STATUSES(EnumChoices):
        UNREVIEWED = 0, 'Unreviewed'
        CHANGED = 1, 'Pending, accepted content changed'
        PASS = 2, 'Pass'
        FAIL = 3, 'Fail'
        REQUESTED = 4, 'Pending, New review requested'

    CONTENT_REVIEW_STATUSES.add_subset('REJECTED', ('FAIL', 'REQUESTED'))
    CONTENT_REVIEW_STATUSES.add_subset(
        'PENDING', ('UNREVIEWED', 'CHANGED', 'REQUESTED')
    )
    CONTENT_REVIEW_STATUSES.add_subset('COMPLETE', ('PASS', 'FAIL'))

    addon = models.OneToOneField(Addon, primary_key=True, on_delete=models.CASCADE)
    counter = models.PositiveIntegerField(default=0)
    last_human_review = models.DateTimeField(null=True)
    last_content_review = models.DateTimeField(null=True, db_index=True)
    content_review_status = models.SmallIntegerField(
        choices=CONTENT_REVIEW_STATUSES.choices,
        db_index=True,
        default=CONTENT_REVIEW_STATUSES.UNREVIEWED,
    )

    def __str__(self):
        return '%s: %d' % (str(self.pk), self.counter) if self.pk else ''

    @classmethod
    def increment_for_addon(cls, addon):
        """
        Increment approval counter for the specified addon, setting the last
        human review date and last content review date to now.
        If an AddonApprovalsCounter already exists, it updates it, otherwise it
        creates and saves a new instance.
        """
        now = datetime.now()
        data = {
            'counter': 1,
            'last_human_review': now,
            'last_content_review': now,
            'content_review_status': cls.CONTENT_REVIEW_STATUSES.PASS,
        }
        # TODO: rewrite this using update_or_create when we're on django5.2
        # - it supports seperate create and update defaults.
        obj, created = cls.objects.get_or_create(addon=addon, defaults=data)
        if not created:
            data['counter'] = F('counter') + 1
            if obj.content_review_status == cls.CONTENT_REVIEW_STATUSES.FAIL:
                # if they failed content review, they have to request a new review.
                del data['content_review_status']
            obj.update(**data)
        return obj

    @classmethod
    def reset_for_addon(cls, addon):
        """
        Reset the approval counter (but not the dates) for the specified addon.
        """
        obj, _ = cls.objects.update_or_create(addon=addon, defaults={'counter': 0})
        return obj

    @classmethod
    def approve_content_for_addon(cls, addon):
        """
        Set last_content_review and content_review_status to
        CONTENT_REVIEW_STATUSES.PASS for this addon.
        """
        obj, _ = cls.objects.update_or_create(
            addon=addon,
            defaults={
                'last_content_review': datetime.now(),
                'content_review_status': (
                    AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.PASS
                ),
            },
        )
        return obj

    @classmethod
    def reject_content_for_addon(cls, addon):
        """
        Set content_review_status to CONTENT_REVIEW_STATUSES.FAIL for this
        addon.
        """
        obj, _ = cls.objects.update_or_create(
            addon=addon,
            defaults={
                'last_content_review': None,
                'content_review_status': (
                    AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.FAIL
                ),
            },
        )
        return obj

    @classmethod
    def reset_content_for_addon(cls, addon):
        """
        Reset the last_content_review date for this addon so it triggers
        another review.
        """
        obj, created = cls.objects.update_or_create(
            addon=addon, defaults={'last_content_review': None}
        )
        if (
            not created
            and obj.content_review_status == cls.CONTENT_REVIEW_STATUSES.PASS
        ):
            obj.update(content_review_status=cls.CONTENT_REVIEW_STATUSES.CHANGED)
        assert obj.last_content_review is None
        return obj

    @classmethod
    def request_new_content_review_for_addon(cls, addon):
        """
        Set content_review_status to CONTENT_REVIEW_STATUSES.REQUESTED for this addon.
        """
        obj, _ = cls.objects.update_or_create(
            addon=addon,
            defaults={
                'content_review_status': (
                    AddonApprovalsCounter.CONTENT_REVIEW_STATUSES.REQUESTED
                ),
            },
        )
        return obj


class DeniedGuid(ModelBase):
    id = PositiveAutoField(primary_key=True)
    guid = models.CharField(max_length=255, unique=True)
    comments = models.TextField(default='', blank=True)

    class Meta:
        db_table = 'denied_guids'

    def __str__(self):
        return self.guid


class Preview(BasePreview, ModelBase):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(Addon, related_name='previews', on_delete=models.CASCADE)
    caption = TranslatedField(max_length=280)
    position = models.IntegerField(default=0)
    sizes = models.JSONField(default=dict)

    class Meta:
        db_table = 'previews'
        ordering = ('position', 'created')
        indexes = [
            models.Index(fields=('addon',), name='previews_addon_idx'),
            models.Index(
                fields=('addon', 'position', 'created'),
                name='addon_position_created_idx',
            ),
        ]

    def get_format(self, for_size):
        return self.sizes.get(
            f'{for_size}_format',
            # If self.sizes doesn't contain the requested format, it's probably
            # because the Preview was just created but not yet resized down.
            # We try to guess the format if it's in ADDON_PREVIEW_SIZES,
            # falling back to `png` like BasePreview does otherwise.
            amo.ADDON_PREVIEW_SIZES.get(f'{for_size}_format', 'png'),
        )


dbsignals.pre_save.connect(
    save_signal, sender=Preview, dispatch_uid='preview_translations'
)


models.signals.post_delete.connect(
    Preview.delete_preview_files, sender=Preview, dispatch_uid='delete_preview_files'
)


class DeniedSlug(ModelBase):
    name = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'addons_denied_slug'

    def __str__(self):
        return self.name

    @classmethod
    def blocked(cls, slug):
        return slug.isdigit() or cls.objects.filter(name=slug).exists()


class FrozenAddon(models.Model):
    """Add-ons in this table never get a hotness score."""

    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)

    class Meta:
        db_table = 'frozen_addons'

    def __str__(self):
        return 'Frozen: %s' % self.addon_id


@receiver(dbsignals.post_save, sender=FrozenAddon)
def freezer(sender, instance, **kw):
    # Adjust the hotness of the FrozenAddon.
    if instance.addon_id:
        Addon.objects.get(id=instance.addon_id).update(hotness=0)


class ReplacementAddon(ModelBase):
    guid = models.CharField(max_length=255, unique=True, null=True)
    path = models.CharField(
        max_length=255,
        null=True,
        help_text='Add-on and collection paths need to end with "/"',
    )

    class Meta:
        db_table = 'replacement_addons'

    @staticmethod
    def path_is_external(path):
        return urlsplit(path).scheme in ['http', 'https']

    def has_external_url(self):
        return self.path_is_external(self.path)


def track_new_status(sender, instance, *args, **kw):
    if kw.get('raw'):
        # The addon is being loaded from a fixure.
        return
    if kw.get('created'):
        track_addon_status_change(instance)


models.signals.post_save.connect(
    track_new_status, sender=Addon, dispatch_uid='track_new_addon_status'
)


@Addon.on_change
def track_status_change(old_attr=None, new_attr=None, **kw):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    if new_status != old_status:
        track_addon_status_change(kw['instance'])


def track_addon_status_change(addon):
    statsd.incr(f'addon_status_change.all.status_{addon.status}')


class AddonGUID(ModelBase):
    """
    Addons + guids will be added to this table whenever an addon is created.
    For deleted addons it will contain an fk to the Addon instance even after
    Addon.guid has been set to null (i.e. when it's been reuploaded).
    """

    guid = models.CharField(max_length=255, null=False, db_index=True)
    addon = models.OneToOneField(
        Addon, null=False, on_delete=models.CASCADE, unique=True
    )
    hashed_guid = models.CharField(max_length=64, null=False)

    class Meta:
        db_table = 'addons_reusedguid'

    def save(self, *args, **kwargs):
        self.hashed_guid = hashlib.sha256(self.guid.encode()).hexdigest()
        super().save(*args, **kwargs)


class AddonBrowserMapping(ModelBase):
    """
    Mapping between an extension ID for a different browser to a Firefox add-on
    on AMO.
    """

    addon = models.ForeignKey(
        Addon,
        on_delete=models.CASCADE,
        help_text='Add-on id this item will point to. If you do not know the '
        'id, paste the slug instead and it will be transformed automatically '
        'for you. You can also use the magnifying glass to see all the '
        'available add-ons if you have access to the add-on admin page.',
    )
    browser = models.PositiveSmallIntegerField(choices=BROWSERS.items())
    extension_id = models.CharField(max_length=255, null=False, db_index=True)

    class Meta:
        unique_together = ('browser', 'extension_id')


class DisabledAddonContent(ModelBase):
    """Link between an addon and the content that was deleted from disk when
    it was force-disabled.

    That link should be removed if the addon is force-enabled, and the content
    restored from backup storage."""

    addon = models.OneToOneField(
        Addon,
        related_name='content_deleted_on_force_disable',
        on_delete=models.CASCADE,
        primary_key=True,
    )
    icon_backup_name = models.CharField(
        max_length=75, default=None, null=True, blank=True
    )


class DeletedPreviewFile(ModelBase):
    """Model holding the backup name for a Preview whose file was deleted from
    disk following a force-disable of the corresponding Addon.

    Used with DisabledAddonContent"""

    disabled_addon_content = models.ForeignKey(
        DisabledAddonContent, on_delete=models.CASCADE
    )
    preview = models.ForeignKey(Preview, on_delete=models.CASCADE)
    backup_name = models.CharField(max_length=75, default=None, null=True, blank=True)


class AddonListingInfo(ModelBase):
    """Model holding information related to the listing page of an Addon."""

    addon = models.OneToOneField(
        Addon, null=False, on_delete=models.CASCADE, unique=True
    )
    noindex_until = models.DateTimeField(blank=True, default=None, null=True)

    @classmethod
    def maybe_mark_as_noindexed(cls, addon):
        # We only consider "recent" add-ons.
        delta = datetime.now() - addon.created
        if delta.days > get_config(
            amo.config_keys.NOINDEX_ON_CONTENT_CHANGE_CUT_OFF_DAYS
        ):
            return

        noindex_until = datetime.now() + timedelta(
            days=get_config(amo.config_keys.NOINDEX_ON_CONTENT_CHANGE_DELAY)
        )
        cls.objects.update_or_create(
            addon=addon, defaults={'noindex_until': noindex_until}
        )
