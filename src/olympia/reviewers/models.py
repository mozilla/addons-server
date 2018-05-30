import json

from collections import OrderedDict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Func
from django.template import loader
from django.utils.translation import ugettext, ugettext_lazy as _

import olympia.core.logger

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.addons.models import Addon, Persona
from olympia.amo.models import ManagerBase, ModelBase, skip_cache
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import cache_ns_key, send_mail
from olympia.files.models import FileValidation
from olympia.ratings.models import Rating
from olympia.reviewers.sql_model import RawSQLModel
from olympia.users.models import UserForeignKey, UserProfile
from olympia.versions.models import Version, version_uploaded


user_log = olympia.core.logger.getLogger('z.users')

log = olympia.core.logger.getLogger('z.reviewers')


VIEW_QUEUE_FLAGS = (
    ('needs_admin_code_review', 'needs-admin-code-review',
        _('Needs Admin Code Review')),
    ('needs_admin_content_review', 'needs-admin-content-review',
        _('Needs Admin Content Review')),
    ('needs_admin_theme_review', 'needs-admin-theme-review',
        _('Needs Admin Static Theme Review')),
    ('is_jetpack', 'jetpack', _('Jetpack Add-on')),
    ('is_restart_required', 'is_restart_required', _('Requires Restart')),
    ('pending_info_request', 'info', _('More Information Requested')),
    ('expired_info_request', 'expired-info', _('Expired Information Request')),
    ('has_reviewer_comment', 'reviewer', _('Contains Reviewer Comment')),
    ('sources_provided', 'sources-provided', _('Sources provided')),
    ('is_webextension', 'webextension', _('WebExtension')),
)


# Django 1.8 does not have Cast(), so this is a simple dumb implementation
# that only handles Cast(..., DateTimeField())
class DateTimeCast(Func):
    function = 'CAST'
    template = '%(function)s(%(expressions)s AS DATETIME(6))'


def get_reviewing_cache_key(addon_id):
    return '%s:review_viewing:%s' % (settings.CACHE_PREFIX, addon_id)


def clear_reviewing_cache(addon_id):
    return cache.delete(get_reviewing_cache_key(addon_id))


def get_reviewing_cache(addon_id):
    return cache.get(get_reviewing_cache_key(addon_id))


def set_reviewing_cache(addon_id, user_id):
    # We want to save it for twice as long as the ping interval,
    # just to account for latency and the like.
    cache.set(get_reviewing_cache_key(addon_id),
              user_id,
              amo.REVIEWER_VIEWING_INTERVAL * 2)


class CannedResponse(ModelBase):
    name = models.CharField(max_length=255)
    response = models.TextField()
    sort_group = models.CharField(max_length=255)
    type = models.PositiveIntegerField(
        choices=amo.CANNED_RESPONSE_CHOICES.items(), db_index=True, default=0)

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)


def get_flags(addon, version):
    """Return a list of tuples (indicating which flags should be displayed for
    a particular add-on."""
    return [(cls, title) for (prop, cls, title) in VIEW_QUEUE_FLAGS
            if getattr(version, prop, getattr(addon, prop, None))]


def get_flags_for_row(record):
    """Like get_flags(), but for the queue pages, using fields directly
    returned by the queues SQL query."""
    return [(cls, title) for (prop, cls, title) in VIEW_QUEUE_FLAGS
            if getattr(record, prop)]


class ViewQueue(RawSQLModel):
    id = models.IntegerField()
    addon_name = models.CharField(max_length=255)
    addon_slug = models.CharField(max_length=30)
    addon_status = models.IntegerField()
    addon_type_id = models.IntegerField()
    needs_admin_code_review = models.NullBooleanField()
    needs_admin_content_review = models.NullBooleanField()
    needs_admin_theme_review = models.NullBooleanField()
    is_restart_required = models.BooleanField()
    is_jetpack = models.BooleanField()
    source = models.CharField(max_length=100)
    is_webextension = models.BooleanField()
    latest_version = models.CharField(max_length=255)
    pending_info_request = models.DateTimeField()
    expired_info_request = models.NullBooleanField()
    has_reviewer_comment = models.BooleanField()
    waiting_time_days = models.IntegerField()
    waiting_time_hours = models.IntegerField()
    waiting_time_min = models.IntegerField()

    def base_query(self):
        return {
            'select': OrderedDict([
                ('id', 'addons.id'),
                ('addon_name', 'tr.localized_string'),
                ('addon_status', 'addons.status'),
                ('addon_type_id', 'addons.addontype_id'),
                ('addon_slug', 'addons.slug'),
                ('needs_admin_code_review',
                    'addons_addonreviewerflags.needs_admin_code_review'),
                ('needs_admin_content_review',
                    'addons_addonreviewerflags.needs_admin_content_review'),
                ('needs_admin_theme_review',
                    'addons_addonreviewerflags.needs_admin_theme_review'),
                ('latest_version', 'versions.version'),
                ('has_reviewer_comment', 'versions.has_editor_comment'),
                ('pending_info_request',
                    'addons_addonreviewerflags.pending_info_request'),
                ('expired_info_request', (
                    'TIMEDIFF(addons_addonreviewerflags.pending_info_request,'
                    'NOW()) < 0')),
                ('is_jetpack', 'MAX(files.jetpack_version IS NOT NULL)'),
                ('is_restart_required', 'MAX(files.is_restart_required)'),
                ('source', 'versions.source'),
                ('is_webextension', 'MAX(files.is_webextension)'),
                ('waiting_time_days',
                    'TIMESTAMPDIFF(DAY, MAX(versions.nomination), NOW())'),
                ('waiting_time_hours',
                    'TIMESTAMPDIFF(HOUR, MAX(versions.nomination), NOW())'),
                ('waiting_time_min',
                    'TIMESTAMPDIFF(MINUTE, MAX(versions.nomination), NOW())'),
            ]),
            'from': [
                'addons',
                """
                LEFT JOIN addons_addonreviewerflags ON (
                    addons.id = addons_addonreviewerflags.addon_id)
                LEFT JOIN versions ON (addons.id = versions.addon_id)
                LEFT JOIN files ON (files.version_id = versions.id)

                JOIN translations AS tr ON (
                    tr.id = addons.name
                    AND tr.locale = addons.defaultlocale)
                """
            ],
            'where': [
                'NOT addons.inactive',  # disabled_by_user
                'versions.channel = %s' % amo.RELEASE_CHANNEL_LISTED,
                'files.status = %s' % amo.STATUS_AWAITING_REVIEW,
            ],
            'group_by': 'id'}

    @property
    def sources_provided(self):
        return bool(self.source)

    @property
    def flags(self):
        return get_flags_for_row(self)


class ViewFullReviewQueue(ViewQueue):

    def base_query(self):
        q = super(ViewFullReviewQueue, self).base_query()
        q['where'].append('addons.status = %s' % amo.STATUS_NOMINATED)
        return q


class ViewPendingQueue(ViewQueue):

    def base_query(self):
        q = super(ViewPendingQueue, self).base_query()
        q['where'].append('addons.status = %s' % amo.STATUS_PUBLIC)
        return q


class ViewUnlistedAllList(RawSQLModel):
    id = models.IntegerField()
    addon_name = models.CharField(max_length=255)
    addon_slug = models.CharField(max_length=30)
    guid = models.CharField(max_length=255)
    version_date = models.DateTimeField()
    _author_ids = models.CharField(max_length=255)
    _author_usernames = models.CharField()
    review_date = models.DateField()
    review_version_num = models.CharField(max_length=255)
    review_log_id = models.IntegerField()
    addon_status = models.IntegerField()
    latest_version = models.CharField(max_length=255)
    needs_admin_code_review = models.NullBooleanField()
    needs_admin_content_review = models.NullBooleanField()
    needs_admin_theme_review = models.NullBooleanField()
    is_deleted = models.BooleanField()

    def base_query(self):
        review_ids = ','.join([str(r) for r in amo.LOG_REVIEWER_REVIEW_ACTION])
        return {
            'select': OrderedDict([
                ('id', 'addons.id'),
                ('addon_name', 'tr.localized_string'),
                ('addon_status', 'addons.status'),
                ('addon_slug', 'addons.slug'),
                ('latest_version', 'versions.version'),
                ('guid', 'addons.guid'),
                ('_author_ids', 'GROUP_CONCAT(authors.user_id)'),
                ('_author_usernames', 'GROUP_CONCAT(users.username)'),
                ('needs_admin_code_review',
                    'addons_addonreviewerflags.needs_admin_code_review'),
                ('needs_admin_content_review',
                    'addons_addonreviewerflags.needs_admin_content_review'),
                ('needs_admin_theme_review',
                    'addons_addonreviewerflags.needs_admin_theme_review'),
                ('is_deleted', 'IF (addons.status=11, true, false)'),
                ('version_date', 'versions.nomination'),
                ('review_date', 'reviewed_versions.created'),
                ('review_version_num', 'reviewed_versions.version'),
                ('review_log_id', 'reviewed_versions.log_id'),
            ]),
            'from': [
                'addons',
                """
                JOIN (
                    SELECT MAX(id) AS latest_version, addon_id FROM versions
                    WHERE channel = {channel}
                    GROUP BY addon_id
                    ) AS latest_version
                    ON latest_version.addon_id = addons.id
                LEFT JOIN addons_addonreviewerflags ON (
                    addons.id = addons_addonreviewerflags.addon_id)
                LEFT JOIN versions
                    ON (latest_version.latest_version = versions.id)
                JOIN translations AS tr ON (
                    tr.id = addons.name AND
                    tr.locale = addons.defaultlocale)
                LEFT JOIN addons_users AS authors
                    ON addons.id = authors.addon_id
                LEFT JOIN users as users ON users.id = authors.user_id
                LEFT JOIN (
                    SELECT versions.id AS id, addon_id, log.created, version,
                           log.id AS log_id
                    FROM versions
                    JOIN log_activity_version AS log_v ON (
                        log_v.version_id=versions.id)
                    JOIN log_activity as log ON (
                        log.id=log_v.activity_log_id)
                    WHERE log.user_id <> {task_user} AND
                        log.action in ({review_actions}) AND
                        versions.channel = {channel}
                    ORDER BY id desc
                    ) AS reviewed_versions
                    ON reviewed_versions.addon_id = addons.id
                """.format(task_user=settings.TASK_USER_ID,
                           review_actions=review_ids,
                           channel=amo.RELEASE_CHANNEL_UNLISTED),
            ],
            'where': [
                'NOT addons.inactive',  # disabled_by_user
                'versions.channel = %s' % amo.RELEASE_CHANNEL_UNLISTED,
                """((reviewed_versions.id = (select max(reviewed_versions.id)))
                    OR
                    (reviewed_versions.id IS NULL))
                """,
                'addons.status <> %s' % amo.STATUS_DISABLED
            ],
            'group_by': 'id'}

    @property
    def authors(self):
        ids = self._explode_concat(self._author_ids)
        usernames = self._explode_concat(self._author_usernames, cast=unicode)
        return list(set(zip(ids, usernames)))


class PerformanceGraph(RawSQLModel):
    id = models.IntegerField()
    yearmonth = models.CharField(max_length=7)
    approval_created = models.DateTimeField()
    user_id = models.IntegerField()
    total = models.IntegerField()

    def base_query(self):
        request_ver = amo.LOG.REQUEST_VERSION.id
        review_ids = [str(r) for r in amo.LOG_REVIEWER_REVIEW_ACTION
                      if r != request_ver]

        return {
            'select': OrderedDict([
                ('yearmonth',
                 "DATE_FORMAT(`log_activity`.`created`, '%%Y-%%m')"),
                ('approval_created', '`log_activity`.`created`'),
                ('user_id', '`log_activity`.`user_id`'),
                ('total', 'COUNT(*)')
            ]),
            'from': [
                'log_activity',
            ],
            'where': [
                'log_activity.action in (%s)' % ','.join(review_ids),
                'user_id <> %s' % settings.TASK_USER_ID  # No auto-approvals.
            ],
            'group_by': 'yearmonth, user_id'
        }


class ReviewerSubscription(ModelBase):
    user = models.ForeignKey(UserProfile)
    addon = models.ForeignKey(Addon)

    class Meta:
        db_table = 'editor_subscriptions'

    def send_notification(self, version):
        user_log.info('Sending addon update notice to %s for %s' %
                      (self.user.email, self.addon.pk))
        context = {
            'name': self.addon.name,
            'url': absolutify(reverse('addons.detail', args=[self.addon.pk],
                                      add_prefix=False)),
            'number': version.version,
            'review': absolutify(reverse('reviewers.review',
                                         args=[self.addon.pk],
                                         add_prefix=False)),
            'SITE_URL': settings.SITE_URL,
        }
        # Not being localised because we don't know the reviewer's locale.
        subject = 'Mozilla Add-ons: %s Updated' % self.addon.name
        template = loader.get_template('reviewers/emails/notify_update.ltxt')
        send_mail(subject, template.render(context),
                  recipient_list=[self.user.email],
                  from_email=settings.ADDONS_EMAIL,
                  use_deny_list=False)


def send_notifications(signal=None, sender=None, **kw):
    if sender.channel != amo.RELEASE_CHANNEL_LISTED:
        return

    subscribers = sender.addon.reviewersubscription_set.all()

    if not subscribers:
        return

    for subscriber in subscribers:
        user = subscriber.user
        is_reviewer = (
            user and not user.deleted and user.email and
            acl.is_user_any_kind_of_reviewer(user))
        if is_reviewer:
            subscriber.send_notification(sender)


version_uploaded.connect(send_notifications, dispatch_uid='send_notifications')


class ReviewerScore(ModelBase):
    user = models.ForeignKey(UserProfile, related_name='_reviewer_scores')
    addon = models.ForeignKey(Addon, blank=True, null=True, related_name='+')
    score = models.IntegerField()
    # For automated point rewards.
    note_key = models.SmallIntegerField(choices=amo.REVIEWED_CHOICES.items(),
                                        default=0)
    # For manual point rewards with a note.
    note = models.CharField(max_length=255)

    class Meta:
        db_table = 'reviewer_scores'
        ordering = ('-created',)

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
    def get_event(cls, addon, status, version=None, post_review=False,
                  content_review=False):
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
                    'event type to award points: %r', exception)
                weight = 0
            if weight > amo.POST_REVIEW_WEIGHT_HIGHEST_RISK:
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
            elif status == amo.STATUS_PUBLIC:
                queue = 'UPDATE'
            else:
                queue = ''

            if (addon.type in [amo.ADDON_EXTENSION, amo.ADDON_PLUGIN,
                               amo.ADDON_API] and queue):
                reviewed_score_name = 'REVIEWED_ADDON_%s' % queue
            elif addon.type == amo.ADDON_DICT and queue:
                reviewed_score_name = 'REVIEWED_DICT_%s' % queue
            elif addon.type in [amo.ADDON_LPAPP, amo.ADDON_LPADDON] and queue:
                reviewed_score_name = 'REVIEWED_LP_%s' % queue
            elif addon.type == amo.ADDON_PERSONA:
                reviewed_score_name = 'REVIEWED_PERSONA'
            elif addon.type == amo.ADDON_STATICTHEME:
                reviewed_score_name = 'REVIEWED_STATICTHEME'
            elif addon.type == amo.ADDON_SEARCH and queue:
                reviewed_score_name = 'REVIEWED_SEARCH_%s' % queue
            elif addon.type == amo.ADDON_THEME and queue:
                reviewed_score_name = 'REVIEWED_XUL_THEME_%s' % queue

        if reviewed_score_name:
            return getattr(amo, reviewed_score_name)
        return None

    @classmethod
    def award_points(cls, user, addon, status, version=None,
                     post_review=False, content_review=False,
                     extra_note=''):
        """Awards points to user based on an event and the queue.

        `event` is one of the `REVIEWED_` keys in constants.
        `status` is one of the `STATUS_` keys in constants.
        `version` is the `Version` object that was affected by the review.
        `post_review` is set to True if the add-on was auto-approved and the
                      reviewer is confirming/rejecting post-approval.
        `content_review` is set to True if it's a content-only review of an
                         auto-approved add-on.

        """
        event = cls.get_event(
            addon, status, version=version, post_review=post_review,
            content_review=content_review)
        score = amo.REVIEWED_SCORES.get(event)

        # Add bonus to reviews greater than our limit to encourage fixing
        # old reviews. Does not apply to content-review/post-review at the
        # moment, because it would need to be calculated differently.
        award_overdue_bonus = (
            version and version.nomination and
            not post_review and not content_review)
        if award_overdue_bonus:
            waiting_time_days = (datetime.now() - version.nomination).days
            days_over = waiting_time_days - amo.REVIEWED_OVERDUE_LIMIT
            if days_over > 0:
                bonus = days_over * amo.REVIEWED_OVERDUE_BONUS
                score = score + bonus

        if score:
            cls.objects.create(user=user, addon=addon, score=score,
                               note_key=event, note=extra_note)
            cls.get_key(invalidate=True)
            user_log.info(
                (u'Awarding %s points to user %s for "%s" for addon %s' % (
                    score, user, amo.REVIEWED_CHOICES[event], addon.id))
                .encode('utf-8'))
        return score

    @classmethod
    def award_moderation_points(cls, user, addon, review_id, undo=False):
        """Awards points to user based on moderated review."""
        event = (amo.REVIEWED_ADDON_REVIEW if not undo else
                 amo.REVIEWED_ADDON_REVIEW_POORLY)
        score = amo.REVIEWED_SCORES.get(event)

        cls.objects.create(user=user, addon=addon, score=score, note_key=event)
        cls.get_key(invalidate=True)
        user_log.info(
            u'Awarding %s points to user %s for "%s" for review %s' % (
                score, user, amo.REVIEWED_CHOICES[event], review_id))

    @classmethod
    def get_total(cls, user):
        """Returns total points by user."""
        key = cls.get_key('get_total:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        val = (ReviewerScore.objects.no_cache().filter(user=user)
                                    .aggregate(total=Sum('score'))
                                    .values())[0]
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

        val = ReviewerScore.objects.no_cache().filter(user=user)
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
        with skip_cache():
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
        with skip_cache():
            val = list(ReviewerScore.objects.raw(sql, [user.id, since]))
        cache.set(key, val, 3600)
        return val

    @classmethod
    def _leaderboard_list(cls, since=None, types=None, addon_type=None):
        """
        Returns base leaderboard list. Each item will be a tuple containing
        (user_id, name, total).
        """

        reviewers = (UserProfile.objects
                                .filter(groups__name__startswith='Reviewers: ')
                                .exclude(groups__name__in=('Staff', 'Admins',
                                         'No Reviewer Incentives'))
                                .distinct())
        qs = (cls.objects
                 .values_list('user__id')
                 .filter(user__in=reviewers)
                 .annotate(total=Sum('score'))
                 .order_by('-total'))

        if since is not None:
            qs = qs.filter(created__gte=since)

        if types is not None:
            qs = qs.filter(note_key__in=types)

        if addon_type is not None:
            qs = qs.filter(addon__type=addon_type)

        users = {reviewer.pk: reviewer for reviewer in reviewers}
        return [
            (item[0], users.get(item[0], UserProfile()).name, item[1])
            for item in qs]

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
            since=week_ago, types=types, addon_type=addon_type)

        scores = []

        user_rank = 0
        in_leaderboard = False
        for rank, row in enumerate(leaderboard, 1):
            user_id, name, total = row
            scores.append({
                'user_id': user_id,
                'name': name,
                'rank': rank,
                'total': int(total),
            })
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
                level = unicode(amo.REVIEWED_LEVELS[user_level]['name'])

            scores.append({
                'user_id': user_id,
                'name': name,
                'total': int(total),
                'level': level,
            })

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
    version = models.OneToOneField(
        Version, on_delete=models.CASCADE, primary_key=True)
    is_locked = models.BooleanField(default=False)
    has_auto_approval_disabled = models.BooleanField(default=False)
    verdict = models.PositiveSmallIntegerField(
        choices=amo.AUTO_APPROVAL_VERDICT_CHOICES,
        default=amo.NOT_AUTO_APPROVED)
    weight = models.IntegerField(default=0)
    confirmed = models.NullBooleanField(default=None)

    class Meta:
        db_table = 'editors_autoapprovalsummary'

    def __unicode__(self):
        return u'%s %s' % (self.version.addon.name, self.version)

    def calculate_weight(self):
        """Calculate the weight value for this version according to various
        risk factors, setting the weight property on the instance and returning
        a dict of risk factors.

        That value is then used in reviewer tools to prioritize add-ons in the
        auto-approved queue."""
        # Note: for the moment, some factors are in direct contradiction with
        # the rules determining whether or not an add-on can be auto-approved
        # in the first place, but we'll relax those rules as we move towards
        # post-review.
        addon = self.version.addon
        one_year_ago = (self.created or datetime.now()) - timedelta(days=365)
        factors = {
            # Add-ons under admin code review: 100 added to weight.
            'admin_code_review': 100 if addon.needs_admin_code_review else 0,
            # Each "recent" abuse reports for the add-on or one of the listed
            # developers adds 10 to the weight, up to a maximum of 100.
            'abuse_reports': min(
                AbuseReport.objects
                .filter(Q(addon=addon) | Q(user__in=addon.listed_authors))
                .filter(created__gte=one_year_ago).count() * 10, 100),
            # 1% of the total of "recent" ratings with a score of 3 or less
            # adds 2 to the weight, up to a maximum of 100.
            'negative_ratings': min(int(
                Rating.objects
                .filter(addon=addon)
                .filter(rating__lte=3, created__gte=one_year_ago)
                .count() / 100.0 * 2.0), 100),
            # Reputation is set by admin - the value is inverted to add from
            # -300 (decreasing priority for "trusted" add-ons) to 0.
            'reputation': (
                max(min(int(addon.reputation or 0) * -100, 0), -300)),
            # Average daily users: value divided by 10000 is added to the
            # weight, up to a maximum of 100.
            'average_daily_users': min(addon.average_daily_users / 10000, 100),
            # Pas rejection history: each "recent" rejected version (disabled
            # with an original status of null, so not disabled by a developer)
            # adds 10 to the weight, up to a maximum of 100.
            'past_rejection_history': min(
                Version.objects
                .filter(addon=addon,
                        files__reviewed__gte=one_year_ago,
                        files__original_status=amo.STATUS_NULL,
                        files__status=amo.STATUS_DISABLED)
                .distinct().count() * 10, 100),
        }
        factors.update(self.calculate_static_analysis_weight_factors())
        self.weight = sum(factors.values())
        return factors

    def calculate_static_analysis_weight_factors(self):
        """Calculate the static analysis risk factors, returning a dict of
        risk factors.

        Used by calculate_weight()."""
        try:
            factors = {
                # Static analysis flags from linter:
                # eval() or document.write(): 20.
                'uses_eval_or_document_write': (
                    20 if self.check_uses_eval_or_document_write(self.version)
                    else 0),
                # Implied eval in setTimeout/setInterval/ on* attributes: 5.
                'uses_implied_eval': (
                    5 if self.check_uses_implied_eval(self.version) else 0),
                # innerHTML / unsafe DOM: 20.
                'uses_innerhtml': (
                    20 if self.check_uses_innerhtml(self.version) else 0),
                # custom CSP: 30.
                'uses_custom_csp': (
                    30 if self.check_uses_custom_csp(self.version) else 0),
                # nativeMessaging permission: 20.
                'uses_native_messaging': (
                    20 if self.check_uses_native_messaging(self.version) else
                    0),
                # remote scripts: 40.
                'uses_remote_scripts': (
                    40 if self.check_uses_remote_scripts(self.version) else 0),
                # violates mozilla conditions of use: 20.
                'violates_mozilla_conditions': (
                    20 if self.check_violates_mozilla_conditions(self.version)
                    else 0),
                # libraries of unreadable code: 10.
                'uses_unknown_minified_code': (
                    10 if self.check_uses_unknown_minified_code(self.version)
                    else 0),
                # Size of code changes: 5kB is one point, up to a max of 100.
                'size_of_code_changes': min(
                    self.calculate_size_of_code_changes() / 5000, 100)
            }
        except AutoApprovalNoValidationResultError:
            # We should have a FileValidationResult... since we don't and
            # something is wrong, increase the weight by 200.
            factors = {
                'no_validation_result': 200,
            }
        return factors

    def find_previous_confirmed_version(self):
        """Return the most recent version in the add-on history that has been
        confirmed, excluding the one this summary is about, or None if there
        isn't one."""
        addon = self.version.addon
        try:
            version = addon.versions.exclude(pk=self.version.pk).filter(
                autoapprovalsummary__confirmed=True).latest()
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
                total_code_size += (
                    data.get('metadata', {}).get('totalScannedFileSize', 0))
            return total_code_size / number_of_files

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
        on it and the current configuration.

        Return a dict containing more information about what critera passed
        or not."""
        if dry_run:
            success_verdict = amo.WOULD_HAVE_BEEN_AUTO_APPROVED
            failure_verdict = amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED
        else:
            success_verdict = amo.AUTO_APPROVED
            failure_verdict = amo.NOT_AUTO_APPROVED

        # Currently the only thing that can prevent approval are a reviewer
        # lock and having auto-approval disabled flag set on the add-on.
        verdict_info = {
            'is_locked': self.is_locked,
            'has_auto_approval_disabled': self.has_auto_approval_disabled,
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
        mapping = {
            'is_locked': ugettext('Is locked by a reviewer.'),
            'has_auto_approval_disabled': ugettext(
                'Has auto-approval disabled flag set.')
        }
        return (mapping[key] for key, value in sorted(verdict_info.items())
                if value)

    @classmethod
    def check_for_linter_flag(cls, version, flag):
        def _check_for_linter_flag_in_file(file_):
            try:
                validation = file_.validation
            except FileValidation.DoesNotExist:
                raise AutoApprovalNoValidationResultError()
            validation_data = json.loads(validation.validation)
            return any(flag in message['id']
                       for message in validation_data.get('messages', []))
        return any(_check_for_linter_flag_in_file(file_)
                   for file_ in version.all_files)

    @classmethod
    def check_for_metadata_property(cls, version, prop):
        def _check_for_property_in_linter_metadata_in_file(file_):
            try:
                validation = file_.validation
            except FileValidation.DoesNotExist:
                raise AutoApprovalNoValidationResultError()
            validation_data = json.loads(validation.validation)
            return validation_data.get(
                'metadata', {}).get(prop)
        return any(_check_for_property_in_linter_metadata_in_file(file_)
                   for file_ in version.all_files)

    @classmethod
    def check_uses_unknown_minified_code(cls, version):
        return cls.check_for_metadata_property(version, 'unknownMinifiedFiles')

    @classmethod
    def check_violates_mozilla_conditions(cls, version):
        return cls.check_for_linter_flag(version, 'MOZILLA_COND_OF_USE')

    @classmethod
    def check_uses_remote_scripts(cls, version):
        return cls.check_for_linter_flag(version, 'REMOTE_SCRIPT')

    @classmethod
    def check_uses_eval_or_document_write(cls, version):
        return (
            cls.check_for_linter_flag(version, 'NO_DOCUMENT_WRITE') or
            cls.check_for_linter_flag(version, 'DANGEROUS_EVAL'))

    @classmethod
    def check_uses_implied_eval(cls, version):
        return cls.check_for_linter_flag(version, 'NO_IMPLIED_EVAL')

    @classmethod
    def check_uses_innerhtml(cls, version):
        return cls.check_for_linter_flag(version, 'UNSAFE_VAR_ASSIGNMENT')

    @classmethod
    def check_uses_custom_csp(cls, version):
        return cls.check_for_linter_flag(version, 'MANIFEST_CSP')

    @classmethod
    def check_uses_native_messaging(cls, version):
        return any('nativeMessaging' in file_.webext_permissions_list
                   for file_ in version.all_files)

    @classmethod
    def check_is_locked(cls, version):
        locked = get_reviewing_cache(version.addon.pk)
        return bool(locked) and locked != settings.TASK_USER_ID

    @classmethod
    def check_has_auto_approval_disabled(cls, version):
        return bool(version.addon.auto_approval_disabled)

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
            'version': version,
            'is_locked': cls.check_is_locked(version),
            'has_auto_approval_disabled': cls.check_has_auto_approval_disabled(
                version)
        }
        instance = cls(**data)
        verdict_info = instance.calculate_verdict(dry_run=dry_run)
        instance.calculate_weight()
        # We can't do instance.save(), because we want to handle the case where
        # it already existed. So we put the verdict and weight we just
        # calculated in data and use update_or_create().
        data['verdict'] = instance.verdict
        data['weight'] = instance.weight
        instance, _ = cls.objects.update_or_create(
            version=version, defaults=data)
        return instance, verdict_info

    @classmethod
    def get_auto_approved_queue(cls, admin_reviewer=False):
        """Return a queryset of Addon objects that have been auto-approved but
        not confirmed by a human yet."""
        success_verdict = amo.AUTO_APPROVED
        qs = (
            Addon.objects.public()
            .filter(
                _current_version__autoapprovalsummary__verdict=success_verdict)
            .exclude(
                _current_version__autoapprovalsummary__confirmed=True)
        )
        if not admin_reviewer:
            qs = qs.exclude(addonreviewerflags__needs_admin_code_review=True)
        return qs

    @classmethod
    def get_content_review_queue(cls, admin_reviewer=False):
        """Return a queryset of Addon objects that have been auto-approved and
        need content review."""
        success_verdict = amo.AUTO_APPROVED
        a_year_ago = datetime.now() - timedelta(days=365)
        qs = (
            Addon.objects.public()
            .filter(
                _current_version__autoapprovalsummary__verdict=success_verdict)
            .filter(
                Q(addonapprovalscounter__last_content_review=None) |
                Q(addonapprovalscounter__last_content_review__lt=a_year_ago))
        )
        if not admin_reviewer:
            qs = qs.exclude(
                addonreviewerflags__needs_admin_content_review=True)
        return qs


class RereviewQueueThemeManager(ManagerBase):

    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super(RereviewQueueThemeManager, self).get_queryset()
        if self.include_deleted:
            return qs
        else:
            return qs.exclude(theme__addon__status=amo.STATUS_DELETED)


class RereviewQueueTheme(ModelBase):
    theme = models.ForeignKey(Persona)
    header = models.CharField(max_length=72, blank=True, default='')

    # Holds whether this reuploaded theme is a duplicate.
    dupe_persona = models.ForeignKey(Persona, null=True,
                                     related_name='dupepersona')

    # The order of those managers is very important: please read the lengthy
    # comment above the Addon managers declaration/instantiation.
    unfiltered = RereviewQueueThemeManager(include_deleted=True)
    objects = RereviewQueueThemeManager()

    class Meta:
        db_table = 'rereview_queue_theme'

    def __str__(self):
        return str(self.id)

    @property
    def header_path(self):
        """Return the path to the header image."""
        return self.theme._image_path(self.header or self.theme.header)

    @property
    def footer_path(self):
        """Return the path to the optional footer image."""
        footer = self.footer or self.theme.footer
        return footer and self.theme._image_path(footer) or ''

    @property
    def header_url(self):
        """Return the url of the header imager."""
        return self.theme._image_url(self.header or self.theme.header)

    @property
    def footer_url(self):
        """Return the url of the optional footer image."""
        footer = self.footer or self.theme.footer
        return footer and self.theme._image_url(footer) or ''


class ThemeLock(ModelBase):
    theme = models.OneToOneField('addons.Persona')
    reviewer = UserForeignKey()
    expiry = models.DateTimeField()

    class Meta:
        db_table = 'theme_locks'


class Whiteboard(ModelBase):
    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE, primary_key=True)
    private = models.TextField(blank=True)
    public = models.TextField(blank=True)

    class Meta:
        db_table = 'review_whiteboard'

    def __unicode__(self):
        return u'[%s] private: |%s| public: |%s|' % (
            self.addon.name, self.private, self.public)
