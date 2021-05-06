import json

from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q, Sum
from django.template import loader
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy as _

from django_jsonfield_backport.models import JSONField

import olympia.core.logger

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.addons.models import Addon, AddonApprovalsCounter
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import cache_ns_key, send_mail
from olympia.constants.base import _ADDON_SEARCH
from olympia.constants.promoted import (
    NOT_PROMOTED,
    PROMOTED_GROUPS_BY_ID,
    RECOMMENDED,
    PRE_REVIEW_GROUPS,
)
from olympia.files.models import FileValidation
from olympia.ratings.models import Rating
from olympia.reviewers.sql_model import RawSQLModel
from olympia.users.models import UserProfile
from olympia.versions.models import Version, version_uploaded


user_log = olympia.core.logger.getLogger('z.users')

log = olympia.core.logger.getLogger('z.reviewers')


VIEW_QUEUE_FLAGS = (
    (
        'needs_admin_code_review',
        'needs-admin-code-review',
        _('Needs Admin Code Review'),
    ),
    (
        'needs_admin_content_review',
        'needs-admin-content-review',
        _('Needs Admin Content Review'),
    ),
    (
        'needs_admin_theme_review',
        'needs-admin-theme-review',
        _('Needs Admin Static Theme Review'),
    ),
    ('is_restart_required', 'is_restart_required', _('Requires Restart')),
    ('sources_provided', 'sources-provided', _('Sources provided')),
    ('is_webextension', 'webextension', _('WebExtension')),
    (
        'auto_approval_delayed_temporarily',
        'auto-approval-delayed-temporarily',
        _('Auto-approval delayed temporarily'),
    ),
    (
        'auto_approval_delayed_indefinitely',
        'auto-approval-delayed-indefinitely',
        _('Auto-approval delayed indefinitely'),
    ),
)


def get_reviewing_cache_key(addon_id):
    return 'review_viewing:{id}'.format(id=addon_id)


def clear_reviewing_cache(addon_id):
    return cache.delete(get_reviewing_cache_key(addon_id))


def get_reviewing_cache(addon_id):
    return cache.get(get_reviewing_cache_key(addon_id))


def set_reviewing_cache(addon_id, user_id):
    # We want to save it for twice as long as the ping interval,
    # just to account for latency and the like.
    cache.set(
        get_reviewing_cache_key(addon_id), user_id, amo.REVIEWER_VIEWING_INTERVAL * 2
    )


class CannedResponse(ModelBase):
    id = PositiveAutoField(primary_key=True)
    name = models.CharField(max_length=255)
    response = models.TextField()
    sort_group = models.CharField(max_length=255)
    type = models.PositiveIntegerField(
        choices=amo.CANNED_RESPONSE_TYPE_CHOICES.items(), db_index=True, default=0
    )

    # Category is used only by code-manager
    category = models.PositiveIntegerField(
        choices=amo.CANNED_RESPONSE_CATEGORY_CHOICES.items(),
        default=amo.CANNED_RESPONSE_CATEGORY_OTHER,
    )

    class Meta:
        db_table = 'cannedresponses'

    def __str__(self):
        return str(self.name)


def get_flags(addon, version):
    """Return a list of tuples (indicating which flags should be displayed for
    a particular add-on."""
    flags = [
        (cls, title)
        for (prop, cls, title) in VIEW_QUEUE_FLAGS
        if getattr(version, prop, getattr(addon, prop, None))
    ]
    # add in the promoted group flag and return
    if promoted := addon.promoted_group(currently_approved=False):
        flags.append((f'promoted-{promoted.api_name}', promoted.name))
    return flags


def get_flags_for_row(record):
    """Like get_flags(), but for the queue pages, using fields directly
    returned by the queues SQL query."""
    flags = [
        (cls, title) for (prop, cls, title) in VIEW_QUEUE_FLAGS if getattr(record, prop)
    ]
    # add in the promoted group flag and return
    if promoted := record.promoted:
        flags.append((f'promoted-{promoted.api_name}', promoted.name))
    return flags


class ViewQueue(RawSQLModel):
    id = models.IntegerField()
    addon_name = models.CharField(max_length=255)
    addon_slug = models.CharField(max_length=30)
    addon_status = models.IntegerField()
    addon_type_id = models.IntegerField()
    auto_approval_delayed_temporarily = models.BooleanField(null=True)
    auto_approval_delayed_indefinitely = models.BooleanField(null=True)
    is_restart_required = models.BooleanField()
    is_webextension = models.BooleanField()
    latest_version = models.CharField(max_length=255)
    needs_admin_code_review = models.BooleanField(null=True)
    needs_admin_content_review = models.BooleanField(null=True)
    needs_admin_theme_review = models.BooleanField(null=True)
    promoted_group_id = models.IntegerField()
    source = models.CharField(max_length=100)
    waiting_time_days = models.IntegerField()
    waiting_time_hours = models.IntegerField()
    waiting_time_min = models.IntegerField()

    recommendable_addons = False

    def base_query(self):
        return {
            'select': OrderedDict(
                [
                    ('id', 'addons.id'),
                    ('addon_name', 'tr.localized_string'),
                    ('addon_status', 'addons.status'),
                    ('addon_type_id', 'addons.addontype_id'),
                    ('addon_slug', 'addons.slug'),
                    (
                        'auto_approval_delayed_temporarily',
                        (
                            'TIMEDIFF(addons_addonreviewerflags.'
                            'auto_approval_delayed_until, NOW()) > 0 AND '
                            'EXTRACT(YEAR FROM addons_addonreviewerflags.'
                            'auto_approval_delayed_until) != 9999'
                        ),
                    ),
                    (
                        'auto_approval_delayed_indefinitely',
                        (
                            'TIMEDIFF(addons_addonreviewerflags.'
                            'auto_approval_delayed_until, NOW()) > 0 AND '
                            'EXTRACT(YEAR FROM addons_addonreviewerflags.'
                            'auto_approval_delayed_until) = 9999'
                        ),
                    ),
                    ('is_restart_required', 'MAX(files.is_restart_required)'),
                    ('is_webextension', 'MAX(files.is_webextension)'),
                    ('latest_version', 'versions.version'),
                    (
                        'needs_admin_code_review',
                        'addons_addonreviewerflags.needs_admin_code_review',
                    ),
                    (
                        'needs_admin_content_review',
                        'addons_addonreviewerflags.needs_admin_content_review',
                    ),
                    (
                        'needs_admin_theme_review',
                        'addons_addonreviewerflags.needs_admin_theme_review',
                    ),
                    ('promoted_group_id', 'promoted.group_id'),
                    ('source', 'versions.source'),
                    (
                        'waiting_time_days',
                        'TIMESTAMPDIFF(DAY, MAX(versions.nomination), NOW())',
                    ),
                    (
                        'waiting_time_hours',
                        'TIMESTAMPDIFF(HOUR, MAX(versions.nomination), NOW())',
                    ),
                    (
                        'waiting_time_min',
                        'TIMESTAMPDIFF(MINUTE, MAX(versions.nomination), NOW())',
                    ),
                ]
            ),
            'from': [
                'addons',
                """
                LEFT JOIN addons_addonreviewerflags ON (
                    addons.id = addons_addonreviewerflags.addon_id)
                LEFT JOIN versions ON (addons.id = versions.addon_id)
                LEFT JOIN versions_versionreviewerflags ON (
                    versions.id = versions_versionreviewerflags.version_id)
                LEFT JOIN files ON (files.version_id = versions.id)
                LEFT JOIN promoted_promotedaddon AS promoted ON (
                    addons.id = promoted.addon_id)

                JOIN translations AS tr ON (
                    tr.id = addons.name
                    AND tr.locale = addons.defaultlocale)
                """,
            ],
            'where': [
                'NOT addons.inactive',  # disabled_by_user
                'versions.channel = %s' % amo.RELEASE_CHANNEL_LISTED,
                'files.status = %s' % amo.STATUS_AWAITING_REVIEW,
                'versions_versionreviewerflags.pending_rejection IS NULL',
                ('NOT ' if not self.recommendable_addons else '')
                + '(promoted.group_id = %s AND promoted.group_id IS NOT NULL)'
                % RECOMMENDED.id,
            ],
            'group_by': 'id',
        }

    @property
    def sources_provided(self):
        return bool(self.source)

    @property
    def promoted(self):
        return PROMOTED_GROUPS_BY_ID.get(self.promoted_group_id, NOT_PROMOTED)

    @property
    def flags(self):
        return get_flags_for_row(self)


def _int_join(list_of_ints):
    return ','.join(str(int(int_)) for int_ in list_of_ints)


class FullReviewQueueMixin:
    def base_query(self):
        query = super().base_query()
        query['where'].append('addons.status = %s' % amo.STATUS_NOMINATED)
        return query


class PendingQueueMixin:
    def base_query(self):
        query = super().base_query()
        query['where'].append('addons.status = %s' % amo.STATUS_APPROVED)
        return query


class CombinedReviewQueueMixin:
    def base_query(self):
        query = super().base_query()
        query['where'].append(
            f'addons.status IN ({_int_join(amo.VALID_ADDON_STATUSES)})'
        )
        return query


class ExtensionQueueMixin:
    def base_query(self):
        query = super().base_query()
        types = _int_join(set(amo.GROUP_TYPE_ADDON))
        flags_table = 'addons_addonreviewerflags'
        promoted_groups = _int_join(group.id for group in PRE_REVIEW_GROUPS)
        query['where'].append(
            f'((addons.addontype_id IN ({types}) '
            'AND files.is_webextension = 0) '
            f'OR {flags_table}.auto_approval_disabled = 1 '
            f'OR {flags_table}.auto_approval_disabled_until_next_approval = 1 '
            f'OR {flags_table}.auto_approval_delayed_until > NOW() '
            f'OR promoted.group_id IN ({promoted_groups})'
            ')'
        )
        return query


class ThemeQueueMixin:
    def base_query(self):
        query = super().base_query()
        query['where'].append('addons.addontype_id = %s' % amo.ADDON_STATICTHEME)
        return query


class ViewExtensionQueue(ExtensionQueueMixin, CombinedReviewQueueMixin, ViewQueue):
    pass


class ViewRecommendedQueue(CombinedReviewQueueMixin, ViewQueue):
    recommendable_addons = True


class ViewThemeFullReviewQueue(ThemeQueueMixin, FullReviewQueueMixin, ViewQueue):
    pass


class ViewThemePendingQueue(ThemeQueueMixin, PendingQueueMixin, ViewQueue):
    pass


class ViewUnlistedAllList(RawSQLModel):
    id = models.IntegerField()
    addon_name = models.CharField(max_length=255)
    addon_slug = models.CharField(max_length=30)
    guid = models.CharField(max_length=255)
    _author_ids = models.CharField(max_length=255)
    _author_usernames = models.CharField()
    addon_status = models.IntegerField()
    needs_admin_code_review = models.BooleanField(null=True)
    needs_admin_content_review = models.BooleanField(null=True)
    needs_admin_theme_review = models.BooleanField(null=True)
    is_deleted = models.BooleanField()

    def base_query(self):
        return {
            'select': OrderedDict(
                [
                    ('id', 'addons.id'),
                    ('addon_name', 'tr.localized_string'),
                    ('addon_status', 'addons.status'),
                    ('addon_slug', 'addons.slug'),
                    ('guid', 'addons.guid'),
                    ('_author_ids', 'GROUP_CONCAT(authors.user_id)'),
                    ('_author_usernames', 'GROUP_CONCAT(users.username)'),
                    (
                        'needs_admin_code_review',
                        'addons_addonreviewerflags.needs_admin_code_review',
                    ),
                    (
                        'needs_admin_content_review',
                        'addons_addonreviewerflags.needs_admin_content_review',
                    ),
                    (
                        'needs_admin_theme_review',
                        'addons_addonreviewerflags.needs_admin_theme_review',
                    ),
                    ('is_deleted', 'IF (addons.status=11, true, false)'),
                ]
            ),
            'from': [
                'addons',
                """
                LEFT JOIN addons_addonreviewerflags ON (
                    addons.id = addons_addonreviewerflags.addon_id)
                LEFT JOIN versions
                    ON (versions.addon_id = addons.id)
                JOIN translations AS tr ON (
                    tr.id = addons.name AND
                    tr.locale = addons.defaultlocale)
                LEFT JOIN addons_users AS authors
                    ON addons.id = authors.addon_id
                LEFT JOIN users as users ON users.id = authors.user_id
                """,
            ],
            'where': [
                'NOT addons.inactive',  # disabled_by_user
                'versions.channel = %s' % amo.RELEASE_CHANNEL_UNLISTED,
                'addons.status <> %s' % amo.STATUS_DISABLED,
            ],
            'group_by': 'id',
        }

    @property
    def authors(self):
        ids = self._explode_concat(self._author_ids)
        usernames = self._explode_concat(self._author_usernames, cast=str)
        return list(set(zip(ids, usernames)))


class PerformanceGraph(RawSQLModel):
    id = models.IntegerField()
    yearmonth = models.CharField(max_length=7)
    approval_created = models.DateTimeField()
    user_id = models.IntegerField()
    total = models.IntegerField()

    def base_query(self):
        request_ver = amo.LOG.REQUEST_VERSION.id
        review_ids = [
            str(r) for r in amo.LOG_REVIEWER_REVIEW_ACTION if r != request_ver
        ]

        return {
            'select': OrderedDict(
                [
                    ('yearmonth', "DATE_FORMAT(`log_activity`.`created`, '%%Y-%%m')"),
                    ('approval_created', '`log_activity`.`created`'),
                    ('user_id', '`log_activity`.`user_id`'),
                    ('total', 'COUNT(*)'),
                ]
            ),
            'from': [
                'log_activity',
            ],
            'where': [
                'log_activity.action in (%s)' % ','.join(review_ids),
                'user_id <> %s' % settings.TASK_USER_ID,  # No auto-approvals.
            ],
            'group_by': 'yearmonth, user_id',
        }


class ReviewerSubscription(ModelBase):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    channel = models.PositiveSmallIntegerField(choices=amo.RELEASE_CHANNEL_CHOICES)

    class Meta:
        db_table = 'editor_subscriptions'

    def send_notification(self, version):
        user_log.info(
            'Sending addon update notice to %s for %s'
            % (self.user.email, self.addon.pk)
        )

        if version.channel == amo.RELEASE_CHANNEL_LISTED:
            listing_url = absolutify(
                reverse('addons.detail', args=[self.addon.pk], add_prefix=False)
            )
        else:
            # If the submission went to the unlisted channel,
            # do not link to the listing.
            listing_url = None
        context = {
            'name': self.addon.name,
            'url': listing_url,
            'number': version.version,
            'review': absolutify(
                reverse(
                    'reviewers.review',
                    kwargs={
                        'addon_id': self.addon.pk,
                        'channel': amo.CHANNEL_CHOICES_API[version.channel],
                    },
                    add_prefix=False,
                )
            ),
            'SITE_URL': settings.SITE_URL,
        }
        # Not being localised because we don't know the reviewer's locale.
        subject = 'Mozilla Add-ons: %s Updated' % self.addon.name
        template = loader.get_template('reviewers/emails/notify_update.ltxt')
        send_mail(
            subject,
            template.render(context),
            recipient_list=[self.user.email],
            from_email=settings.ADDONS_EMAIL,
            use_deny_list=False,
        )


def send_notifications(sender=None, instance=None, signal=None, **kw):
    subscribers = instance.addon.reviewersubscription_set.all()

    if not subscribers:
        return

    listed_perms = [
        amo.permissions.ADDONS_REVIEW,
        amo.permissions.ADDONS_CONTENT_REVIEW,
        amo.permissions.ADDONS_RECOMMENDED_REVIEW,
        amo.permissions.STATIC_THEMES_REVIEW,
        amo.permissions.REVIEWER_TOOLS_VIEW,
    ]

    unlisted_perms = [
        amo.permissions.ADDONS_REVIEW_UNLISTED,
        amo.permissions.REVIEWER_TOOLS_UNLISTED_VIEW,
    ]

    for subscriber in subscribers:
        user = subscriber.user
        is_active_user = user and not user.deleted and user.email
        is_reviewer_and_listed_submission = (
            subscriber.channel == amo.RELEASE_CHANNEL_LISTED
            and instance.channel == amo.RELEASE_CHANNEL_LISTED
            and any(acl.action_allowed_user(user, perm) for perm in listed_perms)
        )
        is_unlisted_reviewer_and_unlisted_submission = (
            subscriber.channel == amo.RELEASE_CHANNEL_UNLISTED
            and instance.channel == amo.RELEASE_CHANNEL_UNLISTED
            and any(acl.action_allowed_user(user, perm) for perm in unlisted_perms)
        )
        if is_active_user and (
            is_reviewer_and_listed_submission
            or is_unlisted_reviewer_and_unlisted_submission
        ):
            subscriber.send_notification(instance)


version_uploaded.connect(send_notifications, dispatch_uid='send_notifications')


class ReviewerScore(ModelBase):
    id = PositiveAutoField(primary_key=True)
    user = models.ForeignKey(
        UserProfile, related_name='_reviewer_scores', on_delete=models.CASCADE
    )
    addon = models.ForeignKey(
        Addon, blank=True, null=True, related_name='+', on_delete=models.CASCADE
    )
    version = models.ForeignKey(
        Version, blank=True, null=True, related_name='+', on_delete=models.CASCADE
    )
    score = models.IntegerField()
    # For automated point rewards.
    note_key = models.SmallIntegerField(choices=amo.REVIEWED_CHOICES.items(), default=0)
    # For manual point rewards with a note.
    note = models.CharField(max_length=255)

    class Meta:
        db_table = 'reviewer_scores'
        ordering = ('-created',)
        indexes = [
            models.Index(fields=('addon',), name='reviewer_scores_addon_id_fk'),
            models.Index(fields=('created',), name='reviewer_scores_created_idx'),
            models.Index(fields=('user',), name='reviewer_scores_user_id_idx'),
            models.Index(fields=('version',), name='reviewer_scores_version_id'),
        ]

    @classmethod
    def get_key(cls, key=None, invalidate=False):
        namespace = 'riscore'
        if not key:  # Assuming we're invalidating the namespace.
            cache_ns_key(namespace, invalidate)
            return
        else:
            # Using cache_ns_key so each cache val is invalidated together.
            ns_key = cache_ns_key(namespace, invalidate)
            return '%s:%s' % (ns_key, key)

    @classmethod
    def get_event(
        cls, addon, status, version=None, post_review=False, content_review=False
    ):
        """Return the review event type constant.

        This is determined by the addon.type and the queue the addon is
        currently in (which is determined from the various parameters sent
        down from award_points()).

        Note: We're not using addon.status or addon.current_version because
        this is called after the status/current_version might have been updated
        by the reviewer action.

        """
        reviewed_score_name = None
        if content_review:
            # Content review always gives the same amount of points.
            reviewed_score_name = 'REVIEWED_CONTENT_REVIEW'
        elif post_review:
            # There are 4 tiers of post-review scores depending on the addon
            # weight.
            try:
                if version is None:
                    raise AutoApprovalSummary.DoesNotExist
                weight = version.autoapprovalsummary.weight
            except AutoApprovalSummary.DoesNotExist as exception:
                log.exception(
                    'No such version/auto approval summary when determining '
                    'event type to award points: %r',
                    exception,
                )
                weight = 0

            if addon.type == amo.ADDON_DICT:
                reviewed_score_name = 'REVIEWED_DICT_FULL'
            elif addon.type in [amo.ADDON_LPAPP, amo.ADDON_LPADDON]:
                reviewed_score_name = 'REVIEWED_LP_FULL'
            elif addon.type == _ADDON_SEARCH:
                reviewed_score_name = 'REVIEWED_SEARCH_FULL'
            elif weight > amo.POST_REVIEW_WEIGHT_HIGHEST_RISK:
                reviewed_score_name = 'REVIEWED_EXTENSION_HIGHEST_RISK'
            elif weight > amo.POST_REVIEW_WEIGHT_HIGH_RISK:
                reviewed_score_name = 'REVIEWED_EXTENSION_HIGH_RISK'
            elif weight > amo.POST_REVIEW_WEIGHT_MEDIUM_RISK:
                reviewed_score_name = 'REVIEWED_EXTENSION_MEDIUM_RISK'
            else:
                reviewed_score_name = 'REVIEWED_EXTENSION_LOW_RISK'
        else:
            if status == amo.STATUS_NOMINATED:
                queue = 'FULL'
            elif status == amo.STATUS_APPROVED:
                queue = 'UPDATE'
            else:
                queue = ''

            if (
                addon.type in [amo.ADDON_EXTENSION, amo.ADDON_PLUGIN, amo.ADDON_API]
                and queue
            ):
                reviewed_score_name = 'REVIEWED_ADDON_%s' % queue
            elif addon.type == amo.ADDON_DICT and queue:
                reviewed_score_name = 'REVIEWED_DICT_%s' % queue
            elif addon.type in [amo.ADDON_LPAPP, amo.ADDON_LPADDON] and queue:
                reviewed_score_name = 'REVIEWED_LP_%s' % queue
            elif addon.type == amo.ADDON_STATICTHEME:
                reviewed_score_name = 'REVIEWED_STATICTHEME'
            elif addon.type == _ADDON_SEARCH and queue:
                reviewed_score_name = 'REVIEWED_SEARCH_%s' % queue

        if reviewed_score_name:
            return getattr(amo, reviewed_score_name)
        return None

    @classmethod
    def award_points(
        cls,
        user,
        addon,
        status,
        version=None,
        post_review=False,
        content_review=False,
        extra_note='',
    ):
        """Awards points to user based on an event and the queue.

        `event` is one of the `REVIEWED_` keys in constants.
        `status` is one of the `STATUS_` keys in constants.
        `version` is the `Version` object that was affected by the review.
        `post_review` is set to True if the add-on was auto-approved and the
                      reviewer is confirming/rejecting post-approval.
        `content_review` is set to True if it's a content-only review of an
                         auto-approved add-on.

        """

        # If a webextension file gets approved manually (e.g. because
        # auto-approval is disabled), 'post-review' is set to False, treating
        # the file as a legacy file which is not what we want. The file is
        # still a webextension and should treated as such, regardless of
        # auto-approval being disabled or not.
        # As a hack, we set 'post_review' to True.
        if version and version.is_webextension and addon.type in amo.GROUP_TYPE_ADDON:
            post_review = True

        user_log.info(
            (
                'Determining award points for user %s for version %s of addon %s'
                % (user, version, addon.id)
            ).encode('utf-8')
        )

        event = cls.get_event(
            addon,
            status,
            version=version,
            post_review=post_review,
            content_review=content_review,
        )
        score = amo.REVIEWED_SCORES.get(event)

        user_log.info(
            (
                'Determined %s award points (event: %s) for user %s for version '
                '%s of addon %s' % (score, event, user, version, addon.id)
            ).encode('utf-8')
        )

        # Add bonus to reviews greater than our limit to encourage fixing
        # old reviews. Does not apply to content-review/post-review at the
        # moment, because it would need to be calculated differently.
        award_overdue_bonus = (
            version and version.nomination and not post_review and not content_review
        )
        if award_overdue_bonus:
            waiting_time_days = (datetime.now() - version.nomination).days
            days_over = waiting_time_days - amo.REVIEWED_OVERDUE_LIMIT
            if days_over > 0:
                bonus = days_over * amo.REVIEWED_OVERDUE_BONUS
                score = score + bonus

        if score is not None:
            cls.objects.create(
                user=user,
                addon=addon,
                score=score,
                note_key=event,
                note=extra_note,
                version=version,
            )
            cls.get_key(invalidate=True)
            user_log.info(
                (
                    'Awarding %s points to user %s for "%s" for addon %s'
                    % (score, user, amo.REVIEWED_CHOICES[event], addon.id)
                ).encode('utf-8')
            )
        return score

    @classmethod
    def award_moderation_points(cls, user, addon, review_id, undo=False):
        """Awards points to user based on moderated review."""
        event = (
            amo.REVIEWED_ADDON_REVIEW if not undo else amo.REVIEWED_ADDON_REVIEW_POORLY
        )
        score = amo.REVIEWED_SCORES.get(event)

        cls.objects.create(user=user, addon=addon, score=score, note_key=event)
        cls.get_key(invalidate=True)
        user_log.info(
            'Awarding %s points to user %s for "%s" for review %s'
            % (score, user, amo.REVIEWED_CHOICES[event], review_id)
        )

    @classmethod
    def get_total(cls, user):
        """Returns total points by user."""
        key = cls.get_key('get_total:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        val = list(
            ReviewerScore.objects.filter(user=user)
            .aggregate(total=Sum('score'))
            .values()
        )[0]
        if val is None:
            val = 0

        cache.set(key, val, None)
        return val

    @classmethod
    def get_recent(cls, user, limit=5, addon_type=None):
        """Returns most recent ReviewerScore records."""
        key = cls.get_key('get_recent:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        val = ReviewerScore.objects.filter(user=user)
        if addon_type is not None:
            val.filter(addon__type=addon_type)

        val = list(val[:limit])
        cache.set(key, val, None)
        return val

    @classmethod
    def get_breakdown(cls, user):
        """Returns points broken down by addon type."""
        key = cls.get_key('get_breakdown:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        sql = """
             SELECT `reviewer_scores`.*,
                    SUM(`reviewer_scores`.`score`) AS `total`,
                    `addons`.`addontype_id` AS `atype`
             FROM `reviewer_scores`
             LEFT JOIN `addons` ON (`reviewer_scores`.`addon_id`=`addons`.`id`)
             WHERE `reviewer_scores`.`user_id` = %s
             GROUP BY `addons`.`addontype_id`
             ORDER BY `total` DESC
        """
        val = list(ReviewerScore.objects.raw(sql, [user.id]))
        cache.set(key, val, None)
        return val

    @classmethod
    def get_breakdown_since(cls, user, since):
        """
        Returns points broken down by addon type since the given datetime.
        """
        key = cls.get_key('get_breakdown:%s:%s' % (user.id, since.isoformat()))
        val = cache.get(key)
        if val is not None:
            return val

        sql = """
             SELECT `reviewer_scores`.*,
                    SUM(`reviewer_scores`.`score`) AS `total`,
                    `addons`.`addontype_id` AS `atype`
             FROM `reviewer_scores`
             LEFT JOIN `addons` ON (`reviewer_scores`.`addon_id`=`addons`.`id`)
             WHERE `reviewer_scores`.`user_id` = %s AND
                   `reviewer_scores`.`created` >= %s
             GROUP BY `addons`.`addontype_id`
             ORDER BY `total` DESC
        """
        val = list(ReviewerScore.objects.raw(sql, [user.id, since]))
        cache.set(key, val, 3600)
        return val

    @classmethod
    def _leaderboard_list(cls, since=None, types=None, addon_type=None):
        """
        Returns base leaderboard list. Each item will be a tuple containing
        (user_id, name, total).
        """

        reviewers = (
            UserProfile.objects.filter(groups__name__startswith='Reviewers: ')
            .exclude(groups__name__in=('Admins', 'No Reviewer Incentives'))
            .distinct()
        )
        qs = (
            cls.objects.values_list('user__id')
            .filter(user__in=reviewers)
            .annotate(total=Sum('score'))
            .order_by('-total')
        )

        if since is not None:
            qs = qs.filter(created__gte=since)

        if types is not None:
            qs = qs.filter(note_key__in=types)

        if addon_type is not None:
            qs = qs.filter(addon__type=addon_type)

        users = {reviewer.pk: reviewer for reviewer in reviewers}
        return [
            (item[0], users.get(item[0], UserProfile()).name, item[1]) for item in qs
        ]

    @classmethod
    def get_leaderboards(cls, user, days=7, types=None, addon_type=None):
        """Returns leaderboards with ranking for the past given days.

        This will return a dict of 3 items::

            {'leader_top': [...],
             'leader_near: [...],
             'user_rank': (int)}

        If the user is not in the leaderboard, or if the user is in the top 5,
        'leader_near' will be an empty list and 'leader_top' will contain 5
        elements instead of the normal 3.

        """
        key = cls.get_key('get_leaderboards:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        week_ago = date.today() - timedelta(days=days)

        leader_top = []
        leader_near = []

        leaderboard = cls._leaderboard_list(
            since=week_ago, types=types, addon_type=addon_type
        )

        scores = []

        user_rank = 0
        in_leaderboard = False
        for rank, row in enumerate(leaderboard, 1):
            user_id, name, total = row
            scores.append(
                {
                    'user_id': user_id,
                    'name': name,
                    'rank': rank,
                    'total': int(total),
                }
            )
            if user_id == user.id:
                user_rank = rank
                in_leaderboard = True

        if not in_leaderboard:
            leader_top = scores[:5]
        else:
            if user_rank <= 5:  # User is in top 5, show top 5.
                leader_top = scores[:5]
            else:
                leader_top = scores[:3]
                leader_near = [scores[user_rank - 2], scores[user_rank - 1]]
                try:
                    leader_near.append(scores[user_rank])
                except IndexError:
                    pass  # User is last on the leaderboard.

        val = {
            'leader_top': leader_top,
            'leader_near': leader_near,
            'user_rank': user_rank,
        }
        cache.set(key, val, None)
        return val

    @classmethod
    def all_users_by_score(cls):
        """
        Returns reviewers ordered by highest total points first.
        """
        leaderboard = cls._leaderboard_list()
        scores = []

        for row in leaderboard:
            user_id, name, total = row
            user_level = len(amo.REVIEWED_LEVELS) - 1
            for i, level in enumerate(amo.REVIEWED_LEVELS):
                if total < level['points']:
                    user_level = i - 1
                    break

            # Only show level if it changes.
            if user_level < 0:
                level = ''
            else:
                level = str(amo.REVIEWED_LEVELS[user_level]['name'])

            scores.append(
                {
                    'user_id': user_id,
                    'name': name,
                    'total': int(total),
                    'level': level,
                }
            )

        prev = None
        for score in reversed(scores):
            if score['level'] == prev:
                score['level'] = ''
            else:
                prev = score['level']

        return scores


class AutoApprovalNotEnoughFilesError(Exception):
    pass


class AutoApprovalNoValidationResultError(Exception):
    pass


class AutoApprovalSummary(ModelBase):
    """Model holding the results of an auto-approval attempt on a Version."""

    version = models.OneToOneField(Version, on_delete=models.CASCADE, primary_key=True)
    is_locked = models.BooleanField(
        default=False, help_text=_('Is locked by a reviewer')
    )
    has_auto_approval_disabled = models.BooleanField(
        default=False, help_text=_('Has auto-approval disabled/delayed flag set')
    )
    is_promoted_prereview = models.BooleanField(
        default=False,
        null=True,  # TODO: remove this once code has deployed to prod.
        help_text=_('Is in a promoted addon group that requires pre-review'),
    )
    should_be_delayed = models.BooleanField(
        default=False, help_text=_("Delayed because it's the first listed version")
    )
    is_blocked = models.BooleanField(
        default=False, help_text=_('Version string and guid match a blocklist Block')
    )
    verdict = models.PositiveSmallIntegerField(
        choices=amo.AUTO_APPROVAL_VERDICT_CHOICES, default=amo.NOT_AUTO_APPROVED
    )
    weight = models.IntegerField(default=0)
    metadata_weight = models.IntegerField(default=0)
    code_weight = models.IntegerField(default=0)
    weight_info = JSONField(default=dict, null=True)
    confirmed = models.BooleanField(null=True, default=None)
    score = models.PositiveSmallIntegerField(default=None, null=True)

    class Meta:
        db_table = 'editors_autoapprovalsummary'

    # List of fields to check when determining whether a version should be
    # auto-approved or not. Each should be a boolean, a value of true means
    # the version will *not* auto-approved. Each should have a corresponding
    # check_<reason>(version) classmethod defined that will be used by
    # create_summary_for_version() to set the corresponding field on the
    # instance.
    auto_approval_verdict_fields = (
        'has_auto_approval_disabled',
        'is_locked',
        'is_promoted_prereview',
        'should_be_delayed',
        'is_blocked',
    )

    def __str__(self):
        return '%s %s' % (self.version.addon.name, self.version)

    def calculate_weight(self):
        """Calculate the weight value for this version according to various
        risk factors, setting the weight (an integer) and weight_info (a dict
        of risk factors strings -> integer values) properties on the instance.

        The weight value is then used in reviewer tools to prioritize add-ons
        in the auto-approved queue, the weight_info shown to reviewers in the
        review page."""
        metadata_weight_factors = self.calculate_metadata_weight_factors()
        code_weight_factors = self.calculate_code_weight_factors()
        self.metadata_weight = sum(metadata_weight_factors.values())
        self.code_weight = sum(code_weight_factors.values())
        self.weight_info = {
            k: v
            for k, v in dict(**metadata_weight_factors, **code_weight_factors).items()
            # No need to keep 0 value items in the breakdown in the db, they won't be
            # displayed anyway.
            if v
        }
        self.weight = self.metadata_weight + self.code_weight
        return self.weight_info

    def calculate_metadata_weight_factors(self):
        addon = self.version.addon
        one_year_ago = (self.created or datetime.now()) - timedelta(days=365)
        six_weeks_ago = (self.created or datetime.now()) - timedelta(days=42)
        factors = {
            # Add-ons under admin code review: 100 added to weight.
            'admin_code_review': 100 if addon.needs_admin_code_review else 0,
            # Each abuse reports for the add-on or one of the listed developers
            # in the last 6 weeks adds 15 to the weight, up to a maximum of
            # 100.
            'abuse_reports': min(
                AbuseReport.objects.filter(
                    Q(addon=addon) | Q(user__in=addon.listed_authors)
                )
                .filter(created__gte=six_weeks_ago)
                .count()
                * 15,
                100,
            ),
            # 1% of the total of "recent" ratings with a score of 3 or less
            # adds 2 to the weight, up to a maximum of 100.
            'negative_ratings': min(
                int(
                    Rating.objects.filter(addon=addon)
                    .filter(rating__lte=3, created__gte=one_year_ago)
                    .count()
                    / 100.0
                    * 2.0
                ),
                100,
            ),
            # Reputation is set by admin - the value is inverted to add from
            # -300 (decreasing priority for "trusted" add-ons) to 0.
            'reputation': (max(min(int(addon.reputation or 0) * -100, 0), -300)),
            # Average daily users: value divided by 10000 is added to the
            # weight, up to a maximum of 100.
            'average_daily_users': min(addon.average_daily_users // 10000, 100),
            # Pas rejection history: each "recent" rejected version (disabled
            # with an original status of null, so not disabled by a developer)
            # adds 10 to the weight, up to a maximum of 100.
            'past_rejection_history': min(
                Version.objects.filter(
                    addon=addon,
                    files__reviewed__gte=one_year_ago,
                    files__original_status=amo.STATUS_NULL,
                    files__status=amo.STATUS_DISABLED,
                )
                .distinct()
                .count()
                * 10,
                100,
            ),
        }
        return factors

    def calculate_code_weight_factors(self):
        """Calculate the static analysis risk factors, returning a dict of
        risk factors.

        Used by calculate_weight()."""
        try:
            innerhtml_count = self.count_uses_innerhtml(self.version)
            unknown_minified_code_count = self.count_uses_unknown_minified_code(
                self.version
            )

            factors = {
                # Static analysis flags from linter:
                # eval() or document.write(): 50.
                'uses_eval_or_document_write': (
                    50 if self.count_uses_eval_or_document_write(self.version) else 0
                ),
                # Implied eval in setTimeout/setInterval/ on* attributes: 5.
                'uses_implied_eval': (
                    5 if self.count_uses_implied_eval(self.version) else 0
                ),
                # innerHTML / unsafe DOM: 50+10 per instance.
                'uses_innerhtml': (
                    50 + 10 * (innerhtml_count - 1) if innerhtml_count else 0
                ),
                # custom CSP: 90.
                'uses_custom_csp': (
                    90 if self.count_uses_custom_csp(self.version) else 0
                ),
                # nativeMessaging permission: 100.
                'uses_native_messaging': (
                    100 if self.check_uses_native_messaging(self.version) else 0
                ),
                # remote scripts: 100.
                'uses_remote_scripts': (
                    100 if self.count_uses_remote_scripts(self.version) else 0
                ),
                # violates mozilla conditions of use: 20.
                'violates_mozilla_conditions': (
                    20 if self.count_violates_mozilla_conditions(self.version) else 0
                ),
                # libraries of unreadable code: 100+10 per instance.
                'uses_unknown_minified_code': (
                    100 + 10 * (unknown_minified_code_count - 1)
                    if unknown_minified_code_count
                    else 0
                ),
                # Size of code changes: 5kB is one point, up to a max of 100.
                'size_of_code_changes': min(
                    self.calculate_size_of_code_changes() // 5000, 100
                ),
                # Seems to be using a coinminer: 2000
                'uses_coinminer': (
                    2000 if self.count_uses_uses_coinminer(self.version) else 0
                ),
            }
        except AutoApprovalNoValidationResultError:
            # We should have a FileValidationResult... since we don't and
            # something is wrong, increase the weight by 500.
            factors = {
                'no_validation_result': 500,
            }
        return factors

    def calculate_score(self):
        """Compute maliciousness score for this version."""
        # Some precision is lost but we don't particularly care that much, it's
        # mainly going to be used as a denormalized field to help the database
        # query, and be displayed in a list.
        self.score = int(self.version.maliciousness_score)
        return self.score

    def get_pretty_weight_info(self):
        """Returns a list of strings containing weight information."""
        if self.weight_info:
            weight_info = sorted(
                ['%s: %d' % (k, v) for k, v in self.weight_info.items() if v]
            )
        else:
            weight_info = [gettext('Weight breakdown not available.')]
        return weight_info

    def find_previous_confirmed_version(self):
        """Return the most recent version in the add-on history that has been
        confirmed, excluding the one this summary is about, or None if there
        isn't one."""
        addon = self.version.addon
        try:
            version = (
                addon.versions.exclude(pk=self.version.pk)
                .filter(autoapprovalsummary__confirmed=True)
                .latest()
            )
        except Version.DoesNotExist:
            version = None
        return version

    def calculate_size_of_code_changes(self):
        """Return the size of code changes between the version being
        approved and the previous public one."""

        def find_code_size(version):
            # There could be multiple files: if that's the case, take the
            # total for all files and divide it by the number of files.
            number_of_files = len(version.all_files) or 1
            total_code_size = 0
            for file_ in version.all_files:
                data = json.loads(file_.validation.validation)
                total_code_size += data.get('metadata', {}).get(
                    'totalScannedFileSize', 0
                )
            return total_code_size // number_of_files

        try:
            old_version = self.find_previous_confirmed_version()
            old_size = find_code_size(old_version) if old_version else 0
            new_size = find_code_size(self.version)
        except FileValidation.DoesNotExist:
            raise AutoApprovalNoValidationResultError()
        # We don't really care about whether it's a negative or positive change
        # in size, we just need the absolute value (if there is no current
        # public version, that value ends up being the total code size of the
        # version we're approving).
        return abs(old_size - new_size)

    def calculate_verdict(self, dry_run=False, pretty=False):
        """Calculate the verdict for this instance based on the values set
        on it previously and the current configuration.

        Return a dict containing more information about what critera passed
        or not."""
        if dry_run:
            success_verdict = amo.WOULD_HAVE_BEEN_AUTO_APPROVED
            failure_verdict = amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED
        else:
            success_verdict = amo.AUTO_APPROVED
            failure_verdict = amo.NOT_AUTO_APPROVED

        verdict_info = {
            key: bool(getattr(self, key)) for key in self.auto_approval_verdict_fields
        }
        if any(verdict_info.values()):
            self.verdict = failure_verdict
        else:
            self.verdict = success_verdict

        if pretty:
            verdict_info = self.verdict_info_prettifier(verdict_info)

        return verdict_info

    @classmethod
    def verdict_info_prettifier(cls, verdict_info):
        """Return a generator of strings representing the a verdict_info
        (as computed by calculate_verdict()) in human-readable form."""
        return (
            str(cls._meta.get_field(key).help_text)
            for key, value in sorted(verdict_info.items())
            if value
        )

    @classmethod
    def _count_linter_flag(cls, version, flag):
        def _count_linter_flag_in_file(file_):
            try:
                validation = file_.validation
            except FileValidation.DoesNotExist:
                raise AutoApprovalNoValidationResultError()
            validation_data = json.loads(validation.validation)
            return sum(
                flag in message['id'] for message in validation_data.get('messages', [])
            )

        return max(_count_linter_flag_in_file(file_) for file_ in version.all_files)

    @classmethod
    def _count_metadata_property(cls, version, prop):
        def _count_property_in_linter_metadata_in_file(file_):
            try:
                validation = file_.validation
            except FileValidation.DoesNotExist:
                raise AutoApprovalNoValidationResultError()
            validation_data = json.loads(validation.validation)
            return len(validation_data.get('metadata', {}).get(prop, []))

        return max(
            _count_property_in_linter_metadata_in_file(file_)
            for file_ in version.all_files
        )

    @classmethod
    def count_uses_unknown_minified_code(cls, version):
        return cls._count_metadata_property(version, 'unknownMinifiedFiles')

    @classmethod
    def count_violates_mozilla_conditions(cls, version):
        return cls._count_linter_flag(version, 'MOZILLA_COND_OF_USE')

    @classmethod
    def count_uses_remote_scripts(cls, version):
        return cls._count_linter_flag(version, 'REMOTE_SCRIPT')

    @classmethod
    def count_uses_eval_or_document_write(cls, version):
        return cls._count_linter_flag(
            version, 'NO_DOCUMENT_WRITE'
        ) or cls._count_linter_flag(version, 'DANGEROUS_EVAL')

    @classmethod
    def count_uses_implied_eval(cls, version):
        return cls._count_linter_flag(version, 'NO_IMPLIED_EVAL')

    @classmethod
    def count_uses_innerhtml(cls, version):
        return cls._count_linter_flag(version, 'UNSAFE_VAR_ASSIGNMENT')

    @classmethod
    def count_uses_custom_csp(cls, version):
        return cls._count_linter_flag(version, 'MANIFEST_CSP')

    @classmethod
    def count_uses_uses_coinminer(cls, version):
        return cls._count_linter_flag(version, 'COINMINER_USAGE_DETECTED')

    @classmethod
    def check_uses_native_messaging(cls, version):
        return any(
            'nativeMessaging' in file_.permissions for file_ in version.all_files
        )

    @classmethod
    def check_is_locked(cls, version):
        """Check whether the add-on is locked by a reviewer.

        Doesn't apply to langpacks, which are submitted as part of Firefox
        release process and should always be auto-approved."""
        is_langpack = version.addon.type == amo.ADDON_LPAPP
        locked_by = get_reviewing_cache(version.addon.pk)
        return (
            not is_langpack and bool(locked_by) and locked_by != settings.TASK_USER_ID
        )

    @classmethod
    def check_has_auto_approval_disabled(cls, version):
        """Check whether the add-on has auto approval disabled or delayed.

        It could be:
        - Disabled by a reviewer (different flag for listed or unlisted)
        - Disabled until next manual approval (only applies to listed, typically
          set when a previous version is on a delayed rejection)
        - Delayed until a future date by scanners (applies to both listed and
          unlisted)
        """
        addon = version.addon
        is_listed = version.channel == amo.RELEASE_CHANNEL_LISTED
        if is_listed:
            auto_approval_disabled = bool(
                addon.auto_approval_disabled
                or addon.auto_approval_disabled_until_next_approval
            )
        else:
            auto_approval_disabled = bool(addon.auto_approval_disabled_unlisted)
        auto_approval_delayed = bool(
            addon.auto_approval_delayed_until
            and datetime.now() < addon.auto_approval_delayed_until
        )
        return auto_approval_disabled or auto_approval_delayed

    @classmethod
    def check_is_promoted_prereview(cls, version):
        """Check whether the add-on is a promoted addon group that requires
        pre-review.

        Only applies to listed versions."""
        if not version.channel == amo.RELEASE_CHANNEL_LISTED:
            return False
        promo_group = version.addon.promoted_group(currently_approved=False)
        return bool(promo_group and promo_group.pre_review)

    @classmethod
    def check_should_be_delayed(cls, version):
        """Check whether the add-on new enough that the auto-approval of the
        version should be delayed for 24 hours to catch spam.

        Doesn't apply to langpacks, which are submitted as part of Firefox
        release process and should always be auto-approved.
        Only applies to listed versions.
        """
        addon = version.addon
        is_langpack = addon.type == amo.ADDON_LPAPP
        now = datetime.now()
        nomination = version.nomination or addon.created
        try:
            content_review = addon.addonapprovalscounter.last_content_review
        except AddonApprovalsCounter.DoesNotExist:
            content_review = None
        return (
            not is_langpack
            and version.channel == amo.RELEASE_CHANNEL_LISTED
            and version.addon.status == amo.STATUS_NOMINATED
            and now - nomination < timedelta(hours=24)
            and content_review is None
        )

    @classmethod
    def check_is_blocked(cls, version):
        """Check if the version matches a Block in the blocklist.  Such uploads
        would have been prevented, but if it was uploaded before the Block was
        created, it's possible it'll still be pending."""
        return version.is_blocked

    @classmethod
    def create_summary_for_version(cls, version, dry_run=False):
        """Create a AutoApprovalSummary instance in db from the specified
        version.

        Return a tuple with the AutoApprovalSummary instance as first item,
        and a dict containing information about the auto approval verdict as
        second item.

        If dry_run parameter is True, then the instance is created/updated
        normally but when storing the verdict the WOULD_ constants are used
        instead.

        If not using dry_run it's the caller responsability to approve the
        version to make sure the AutoApprovalSummary is not overwritten later
        when the auto-approval process fires again."""
        if len(version.all_files) == 0:
            raise AutoApprovalNotEnoughFilesError()

        data = {
            field: getattr(cls, f'check_{field}')(version)
            for field in cls.auto_approval_verdict_fields
        }
        instance = cls(version=version, **data)
        verdict_info = instance.calculate_verdict(dry_run=dry_run)
        instance.calculate_weight()
        instance.calculate_score()
        # We can't do instance.save(), because we want to handle the case where
        # it already existed. So we put the verdict and weight we just
        # calculated in data and use update_or_create().
        data['score'] = instance.score
        data['verdict'] = instance.verdict
        data['weight'] = instance.weight
        data['metadata_weight'] = instance.metadata_weight
        data['code_weight'] = instance.code_weight
        data['weight_info'] = instance.weight_info
        instance, _ = cls.objects.update_or_create(version=version, defaults=data)
        return instance, verdict_info


class Whiteboard(ModelBase):
    addon = models.OneToOneField(Addon, on_delete=models.CASCADE, primary_key=True)
    private = models.TextField(blank=True)
    public = models.TextField(blank=True)

    class Meta:
        db_table = 'review_whiteboard'

    def __str__(self):
        return '[%s] private: |%s| public: |%s|' % (
            self.addon.name,
            self.private,
            self.public,
        )
