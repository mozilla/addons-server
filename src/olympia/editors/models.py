import json
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Sum
from django.template import Context, loader
from django.utils.datastructures import SortedDict
from django.utils.translation import ugettext_lazy as _lazy

import olympia.core.logger
from olympia import amo
from olympia.amo.models import ManagerBase, ModelBase, skip_cache
from olympia.access.models import Group
from olympia.activity.models import ActivityLog
from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import cache_ns_key, send_mail
from olympia.addons.models import Addon, AddonApprovalsCounter, Persona
from olympia.editors.sql_model import RawSQLModel
from olympia.files.models import FileValidation
from olympia.users.models import UserForeignKey, UserProfile
from olympia.versions.models import Version, version_uploaded


user_log = olympia.core.logger.getLogger('z.users')


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


class AddonCannedResponseManager(ManagerBase):
    def get_queryset(self):
        qs = super(AddonCannedResponseManager, self).get_queryset()
        return qs.filter(type=amo.CANNED_RESPONSE_ADDON)


class AddonCannedResponse(CannedResponse):
    objects = AddonCannedResponseManager()

    class Meta:
        proxy = True


class EventLog(models.Model):
    type = models.CharField(max_length=60)
    action = models.CharField(max_length=120)
    field = models.CharField(max_length=60, blank=True)
    user = models.ForeignKey(UserProfile)
    changed_id = models.IntegerField()
    added = models.CharField(max_length=765, blank=True)
    removed = models.CharField(max_length=765, blank=True)
    notes = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = u'eventlog'

    @staticmethod
    def new_editors():
        action = amo.LOG.GROUP_USER_ADDED
        group = Group.objects.get(name='Add-on Reviewers')
        items = (ActivityLog.objects.for_group(group)
                            .filter(action=action.id)
                            .order_by('-created')[:5])

        return [dict(user=i.arguments[1],
                     created=i.created)
                for i in items if i.arguments[1] in group.users.all()]


def get_flags(record):
    """Return a list of tuples (indicating which flags should be displayed for
    a particular add-on."""
    props = (
        ('admin_review', 'admin-review', _lazy('Admin Review')),
        ('is_jetpack', 'jetpack', _lazy('Jetpack Add-on')),
        ('requires_restart', 'requires_restart',
         _lazy('Requires Restart')),
        ('has_info_request', 'info', _lazy('More Information Requested')),
        ('has_editor_comment', 'editor', _lazy('Contains Reviewer Comment')),
        ('sources_provided', 'sources-provided',
         _lazy('Sources provided')),
        ('is_webextension', 'webextension', _lazy('WebExtension')),
    )

    return [(cls, title) for (prop, cls, title) in props
            if getattr(record, prop)]


class ViewQueue(RawSQLModel):
    id = models.IntegerField()
    addon_name = models.CharField(max_length=255)
    addon_slug = models.CharField(max_length=30)
    addon_status = models.IntegerField()
    addon_type_id = models.IntegerField()
    admin_review = models.BooleanField()
    is_restartless = models.BooleanField()
    is_jetpack = models.BooleanField()
    source = models.CharField(max_length=100)
    is_webextension = models.BooleanField()
    latest_version = models.CharField(max_length=255)
    has_info_request = models.BooleanField()
    has_editor_comment = models.BooleanField()
    waiting_time_days = models.IntegerField()
    waiting_time_hours = models.IntegerField()
    waiting_time_min = models.IntegerField()

    def base_query(self):
        return {
            'select': SortedDict([
                ('id', 'addons.id'),
                ('addon_name', 'tr.localized_string'),
                ('addon_status', 'addons.status'),
                ('addon_type_id', 'addons.addontype_id'),
                ('addon_slug', 'addons.slug'),
                ('admin_review', 'addons.adminreview'),
                ('latest_version', 'versions.version'),
                ('has_editor_comment', 'versions.has_editor_comment'),
                ('has_info_request', 'versions.has_info_request'),
                ('is_jetpack', 'MAX(files.jetpack_version IS NOT NULL)'),
                ('is_restartless', 'MAX(files.no_restart)'),
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
    def requires_restart(self):
        return not self.is_restartless

    @property
    def sources_provided(self):
        return bool(self.source)

    @property
    def flags(self):
        return get_flags(self)


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
    admin_review = models.BooleanField()
    is_deleted = models.BooleanField()

    def base_query(self):
        review_ids = ','.join([str(r) for r in amo.LOG_EDITOR_REVIEW_ACTION])
        return {
            'select': SortedDict([
                ('id', 'addons.id'),
                ('addon_name', 'tr.localized_string'),
                ('addon_status', 'addons.status'),
                ('addon_slug', 'addons.slug'),
                ('latest_version', 'versions.version'),
                ('guid', 'addons.guid'),
                ('_author_ids', 'GROUP_CONCAT(authors.user_id)'),
                ('_author_usernames', 'GROUP_CONCAT(users.username)'),
                ('admin_review', 'addons.adminreview'),
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
        review_ids = [str(r) for r in amo.LOG_EDITOR_REVIEW_ACTION
                      if r != request_ver]

        return {
            'select': SortedDict([
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


class EditorSubscription(ModelBase):
    user = models.ForeignKey(UserProfile)
    addon = models.ForeignKey(Addon)

    class Meta:
        db_table = 'editor_subscriptions'

    def send_notification(self, version):
        user_log.info('Sending addon update notice to %s for %s' %
                      (self.user.email, self.addon.pk))
        context = Context({
            'name': self.addon.name,
            'url': absolutify(reverse('addons.detail', args=[self.addon.pk],
                                      add_prefix=False)),
            'number': version.version,
            'review': absolutify(reverse('editors.review',
                                         args=[self.addon.pk],
                                         add_prefix=False)),
            'SITE_URL': settings.SITE_URL,
        })
        # Not being localised because we don't know the editors locale.
        subject = 'Mozilla Add-ons: %s Updated' % self.addon.name
        template = loader.get_template('editors/emails/notify_update.ltxt')
        send_mail(subject, template.render(Context(context)),
                  recipient_list=[self.user.email],
                  from_email=settings.EDITORS_EMAIL,
                  use_deny_list=False)


def send_notifications(signal=None, sender=None, **kw):
    if sender.is_beta:
        return

    subscribers = sender.addon.editorsubscription_set.all()

    if not subscribers:
        return

    for subscriber in subscribers:
        subscriber.send_notification(sender)
        subscriber.delete()


version_uploaded.connect(send_notifications, dispatch_uid='send_notifications')


class ReviewerScore(ModelBase):
    user = models.ForeignKey(UserProfile, related_name='_reviewer_scores')
    addon = models.ForeignKey(Addon, blank=True, null=True, related_name='+')
    score = models.SmallIntegerField()
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
    def get_event(cls, addon, status, **kwargs):
        """Return the review event type constant.

        This is determined by the addon.type and the queue the addon is
        currently in (which is determined from the status).

        Note: We're not using addon.status because this is called after the
        status has been updated by the reviewer action.

        """
        queue = ''
        if status == amo.STATUS_NOMINATED:
            queue = 'FULL'
        elif status == amo.STATUS_PUBLIC:
            queue = 'UPDATE'

        if (addon.type in [amo.ADDON_EXTENSION, amo.ADDON_PLUGIN,
                           amo.ADDON_API] and queue):
            return getattr(amo, 'REVIEWED_ADDON_%s' % queue)
        elif addon.type == amo.ADDON_DICT and queue:
            return getattr(amo, 'REVIEWED_DICT_%s' % queue)
        elif addon.type in [amo.ADDON_LPAPP, amo.ADDON_LPADDON] and queue:
            return getattr(amo, 'REVIEWED_LP_%s' % queue)
        elif addon.type == amo.ADDON_PERSONA:
            return amo.REVIEWED_PERSONA
        elif addon.type == amo.ADDON_SEARCH and queue:
            return getattr(amo, 'REVIEWED_SEARCH_%s' % queue)
        elif addon.type == amo.ADDON_THEME and queue:
            return getattr(amo, 'REVIEWED_THEME_%s' % queue)
        else:
            return None

    @classmethod
    def award_points(cls, user, addon, status, version=None, **kwargs):
        """Awards points to user based on an event and the queue.

        `event` is one of the `REVIEWED_` keys in constants.
        `status` is one of the `STATUS_` keys in constants.

        """
        event = cls.get_event(addon, status, **kwargs)
        score = amo.REVIEWED_SCORES.get(event)

        # Add bonus to reviews greater than our limit to encourage fixing
        # old reviews.
        if version and version.nomination:
            waiting_time_days = (datetime.now() - version.nomination).days
            days_over = waiting_time_days - amo.REVIEWED_OVERDUE_LIMIT
            if days_over > 0:
                bonus = days_over * amo.REVIEWED_OVERDUE_BONUS
                score = score + bonus

        if score:
            cls.objects.create(user=user, addon=addon, score=score,
                               note_key=event)
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
    def _leaderboard_query(cls, since=None, types=None, addon_type=None):
        """
        Returns common SQL to leaderboard calls.
        """
        query = (cls.objects
                    .values_list('user__id', 'user__display_name')
                    .annotate(total=Sum('score'))
                    .exclude(user__groups__name__in=('No Reviewer Incentives',
                                                     'Staff', 'Admins'))
                    .order_by('-total'))

        if since is not None:
            query = query.filter(created__gte=since)

        if types is not None:
            query = query.filter(note_key__in=types)

        if addon_type is not None:
            query = query.filter(addon__type=addon_type)

        return query

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

        query = cls._leaderboard_query(since=week_ago, types=types,
                                       addon_type=addon_type)
        scores = []

        user_rank = 0
        in_leaderboard = False
        for rank, row in enumerate(query, 1):
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
        query = cls._leaderboard_query()
        scores = []

        for row in query:
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
                level = amo.REVIEWED_LEVELS[user_level]['name']

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
    uses_custom_csp = models.BooleanField(default=False)
    uses_native_messaging = models.BooleanField(default=False)
    uses_content_script_for_all_urls = models.BooleanField(default=False)
    average_daily_users = models.PositiveIntegerField(default=0)
    approved_updates = models.PositiveIntegerField(default=0)
    verdict = models.PositiveSmallIntegerField(
        choices=amo.AUTO_APPROVAL_VERDICT_CHOICES,
        default=amo.NOT_AUTO_APPROVED)

    def calculate_verdict(
            self, max_average_daily_users=0, min_approved_updates=0,
            dry_run=False):
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

        # We need everything in that dict to be False for verdict to be
        # successful.
        verdict_info = {
            'uses_custom_csp': self.uses_custom_csp,
            'uses_native_messaging': self.uses_native_messaging,
            'uses_content_script_for_all_urls':
                self.uses_content_script_for_all_urls,
            'too_many_average_daily_users':
                self.average_daily_users >= max_average_daily_users,
            'too_few_approved_updates':
                self.approved_updates < min_approved_updates,
        }
        if any(verdict_info.values()):
            self.verdict = failure_verdict
        else:
            self.verdict = success_verdict

        return verdict_info

    @classmethod
    def check_uses_custom_csp(cls, version):
        def _check_uses_custom_csp_in_file(file_):
            try:
                validation = file_.validation
            except FileValidation.DoesNotExist:
                raise AutoApprovalNoValidationResultError()
            validation_data = json.loads(validation.validation)
            return any('MANIFEST_CSP' in message['id']
                       for message in validation_data.get('messages', []))
        return any(_check_uses_custom_csp_in_file(file_)
                   for file_ in version.all_files)

    @classmethod
    def check_uses_native_messaging(cls, version):
        return any('nativeMessaging' in file_.webext_permissions_list
                   for file_ in version.all_files)

    @classmethod
    def check_uses_content_script_for_all_urls(cls, version):
        return any(p.name == 'all_urls' for file_ in version.all_files
                   for p in file_.webext_permissions)

    @classmethod
    def create_summary_for_version(
            cls, version, max_average_daily_users=0,
            min_approved_updates=0, dry_run=False):
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

        addon = version.addon
        try:
            approved_updates = addon.addonapprovalscounter.counter
        except AddonApprovalsCounter.DoesNotExist:
            approved_updates = 0

        data = {
            'version': version,
            'uses_custom_csp': cls.check_uses_custom_csp(version),
            'uses_native_messaging': cls.check_uses_native_messaging(version),
            'uses_content_script_for_all_urls':
                cls.check_uses_content_script_for_all_urls(version),
            'average_daily_users': addon.average_daily_users,
            'approved_updates': approved_updates,
        }
        instance = cls(**data)
        verdict_info = instance.calculate_verdict(
            dry_run=dry_run, max_average_daily_users=max_average_daily_users,
            min_approved_updates=min_approved_updates)
        # We can't do instance.save(), because we want to handle the case where
        # it already existed. So we put the verdict we just calculated in data
        # and use update_or_create().
        data['verdict'] = instance.verdict
        instance, _ = cls.objects.update_or_create(
            version=version, defaults=data)
        return instance, verdict_info


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
    footer = models.CharField(max_length=72, blank=True, default='')

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
