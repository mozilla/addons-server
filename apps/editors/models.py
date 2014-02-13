import copy
import datetime

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Sum
from django.template import Context, loader
from django.utils.datastructures import SortedDict

import commonware.log
from tower import ugettext_lazy as _lazy

import amo
import amo.models
from access.models import Group
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import cache_ns_key, send_mail
from addons.models import Addon, Persona
from devhub.models import ActivityLog
from editors.sql_model import RawSQLModel
from translations.fields import save_signal, TranslatedField
from users.models import UserForeignKey, UserProfile
from versions.models import version_uploaded


user_log = commonware.log.getLogger('z.users')


class CannedResponse(amo.models.ModelBase):

    name = TranslatedField()
    response = TranslatedField(short=False)
    sort_group = models.CharField(max_length=255)
    type = models.PositiveIntegerField(
        choices=amo.CANNED_RESPONSE_CHOICES.items(), db_index=True, default=0)

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)

models.signals.pre_save.connect(save_signal, sender=CannedResponse,
                                dispatch_uid='cannedresponses_translations')


class AddonCannedResponseManager(amo.models.ManagerBase):
    def get_query_set(self):
        qs = super(AddonCannedResponseManager, self).get_query_set()
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
                for i in items]


class ViewQueue(RawSQLModel):
    id = models.IntegerField()
    addon_name = models.CharField(max_length=255)
    addon_slug = models.CharField(max_length=30)
    addon_status = models.IntegerField()
    addon_type_id = models.IntegerField()
    admin_review = models.BooleanField()
    is_site_specific = models.BooleanField()
    external_software = models.BooleanField()
    binary = models.BooleanField()
    binary_components = models.BooleanField()
    premium_type = models.IntegerField()
    is_restartless = models.BooleanField()
    is_jetpack = models.BooleanField()
    latest_version = models.CharField(max_length=255)
    _file_platform_ids = models.CharField(max_length=255)
    has_info_request = models.BooleanField()
    has_editor_comment = models.BooleanField()
    _application_ids = models.CharField(max_length=255)
    waiting_time_days = models.IntegerField()
    waiting_time_hours = models.IntegerField()
    waiting_time_min = models.IntegerField()
    is_version_specific = False

    def base_query(self):
        return {
            'select': SortedDict([
                ('id', 'addons.id'),
                ('addon_name', 'tr.localized_string'),
                ('addon_status', 'addons.status'),
                ('addon_type_id', 'addons.addontype_id'),
                ('addon_slug', 'addons.slug'),
                ('admin_review', 'addons.adminreview'),
                ('is_site_specific', 'addons.sitespecific'),
                ('external_software', 'addons.externalsoftware'),
                ('binary', 'files.binary'),
                ('binary_components', 'files.binary_components'),
                ('premium_type', 'addons.premium_type'),
                ('latest_version', 'versions.version'),
                ('has_editor_comment', 'versions.has_editor_comment'),
                ('has_info_request', 'versions.has_info_request'),
                ('_file_platform_ids', """GROUP_CONCAT(DISTINCT
                                          files.platform_id)"""),
                ('is_jetpack', 'MAX(files.jetpack_version IS NOT NULL)'),
                ('is_restartless', 'MAX(files.no_restart)'),
                ('_application_ids', """GROUP_CONCAT(DISTINCT
                                        apps.application_id)"""),
            ]),
            'from': [
                'addons',
                'JOIN versions ON (versions.id = addons.latest_version)',
                'JOIN files ON (files.version_id = versions.id)',
                """LEFT JOIN applications_versions as apps
                            ON versions.id = apps.version_id""",

                #  Translations
                """JOIN translations AS tr ON (
                            tr.id = addons.name
                            AND tr.locale = addons.defaultlocale)"""
            ],
            'where': [
                'NOT addons.inactive',  # disabled_by_user
                'addons.addontype_id <> 11',  # No webapps for AMO.
            ],
            'group_by': 'id'}

    @property
    def is_premium(self):
        return self.premium_type in amo.ADDON_PREMIUMS

    @property
    def file_platform_ids(self):
        return self._explode_concat(self._file_platform_ids)

    @property
    def application_ids(self):
        return self._explode_concat(self._application_ids)

    @property
    def is_traditional_restartless(self):
        return self.is_restartless and not self.is_jetpack

    @property
    def flags(self):
        props = (
            ('admin_review', 'admin-review', _lazy('Admin Review')),
            ('is_jetpack', 'jetpack', _lazy('Jetpack Add-on')),
            ('is_traditional_restartless', 'restartless',
             _lazy('Restartless Add-on')),
            ('is_premium', 'premium', _lazy('Premium Add-on')),
            ('has_info_request', 'info', _lazy('More Information Requested')),
            ('has_editor_comment', 'editor', _lazy('Contains Editor Comment')),
        )

        return [(cls, title) for (prop, cls, title) in props
                if getattr(self, prop)]


class ViewFullReviewQueue(ViewQueue):

    def base_query(self):
        q = super(ViewFullReviewQueue, self).base_query()
        q['select'].update({
            'waiting_time_days':
                'TIMESTAMPDIFF(DAY, MAX(versions.nomination), NOW())',
            'waiting_time_hours':
                'TIMESTAMPDIFF(HOUR, MAX(versions.nomination), NOW())',
            'waiting_time_min':
                'TIMESTAMPDIFF(MINUTE, MAX(versions.nomination), NOW())',
        })
        q['where'].extend(['files.status <> %s' % amo.STATUS_BETA,
                           'addons.status IN (%s, %s)' % (
                               amo.STATUS_NOMINATED,
                               amo.STATUS_LITE_AND_NOMINATED)])
        return q


class VersionSpecificQueue(ViewQueue):
    is_version_specific = True

    def base_query(self):
        q = copy.deepcopy(super(VersionSpecificQueue, self).base_query())
        q['select'].update({
            'waiting_time_days':
                'TIMESTAMPDIFF(DAY, MAX(files.created), NOW())',
            'waiting_time_hours':
                'TIMESTAMPDIFF(HOUR, MAX(files.created), NOW())',
            'waiting_time_min':
                'TIMESTAMPDIFF(MINUTE, MAX(files.created), NOW())',
        })
        return q


class ViewPendingQueue(VersionSpecificQueue):

    def base_query(self):
        q = super(ViewPendingQueue, self).base_query()
        q['where'].extend(['files.status = %s' % amo.STATUS_UNREVIEWED,
                           'addons.status = %s' % amo.STATUS_PUBLIC])
        return q


class ViewPreliminaryQueue(VersionSpecificQueue):

    def base_query(self):
        q = super(ViewPreliminaryQueue, self).base_query()
        q['where'].extend(['files.status = %s' % amo.STATUS_UNREVIEWED,
                           'addons.status IN (%s, %s)' % (
                               amo.STATUS_LITE,
                               amo.STATUS_UNREVIEWED)])
        return q


class ViewFastTrackQueue(VersionSpecificQueue):

    def base_query(self):
        q = super(ViewFastTrackQueue, self).base_query()
        # Fast track includes jetpack-based addons that do not require chrome.
        q['where'].extend(['files.no_restart = 1',
                           'files.jetpack_version IS NOT NULL',
                           'files.requires_chrome = 0',
                           'files.status = %s' % amo.STATUS_UNREVIEWED,
                           'addons.status IN (%s, %s, %s, %s)' % (
                               amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                               amo.STATUS_NOMINATED,
                               amo.STATUS_LITE_AND_NOMINATED)])
        return q


class PerformanceGraph(ViewQueue):
    id = models.IntegerField()
    yearmonth = models.CharField(max_length=7)
    approval_created = models.DateTimeField()
    user_id = models.IntegerField()
    total = models.IntegerField()

    def base_query(self):
        request_ver = amo.LOG.REQUEST_VERSION.id
        review_ids = [str(r) for r in amo.LOG_REVIEW_QUEUE if r != request_ver]

        return {
            'select': SortedDict([
                ('yearmonth',
                 "DATE_FORMAT(`log_activity`.`created`, '%%Y-%%m')"),
                ('approval_created', '`log_activity`.`created`'),
                ('user_id', '`users`.`id`'),
                ('total', 'COUNT(*)')]),
            'from': [
                'log_activity',
                'LEFT JOIN `users` ON (`users`.`id`=`log_activity`.`user_id`)'],
            'where': ['log_activity.action in (%s)' % ','.join(review_ids)],
            'group_by': 'yearmonth, user_id'
        }


class EditorSubscription(amo.models.ModelBase):
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
                  use_blacklist=False)


def send_notifications(signal=None, sender=None, **kw):
    if sender.is_beta:
        return

    # See bug 741679 for implementing this in Marketplace. This is deactivated
    # in the meantime because EditorSubscription.send_notification() uses
    # AMO-specific code.
    if settings.MARKETPLACE:
        return

    subscribers = sender.addon.editorsubscription_set.all()

    if not subscribers:
        return

    for subscriber in subscribers:
        subscriber.send_notification(sender)
        subscriber.delete()


version_uploaded.connect(send_notifications, dispatch_uid='send_notifications')


class ReviewerScore(amo.models.ModelBase):
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
        if status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE]:
            queue = 'PRELIM'
        elif status in [amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED]:
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
        elif addon.type == amo.ADDON_WEBAPP:
            if addon.is_packaged:
                if status == amo.STATUS_PUBLIC:
                    return amo.REVIEWED_WEBAPP_UPDATE
                else:  # If it's not PUBLIC, assume it's a new submission.
                    return amo.REVIEWED_WEBAPP_PACKAGED
            else:  # It's a hosted app.
                in_rereview = kwargs.pop('in_rereview', False)
                if status == amo.STATUS_PUBLIC and in_rereview:
                    return amo.REVIEWED_WEBAPP_REREVIEW
                else:
                    return amo.REVIEWED_WEBAPP_HOSTED
        else:
            return None

    @classmethod
    def award_points(cls, user, addon, status, **kwargs):
        """Awards points to user based on an event and the queue.

        `event` is one of the `REVIEWED_` keys in constants.
        `status` is one of the `STATUS_` keys in constants.

        """
        event = cls.get_event(addon, status, **kwargs)
        score = amo.REVIEWED_SCORES.get(event)
        if score:
            cls.objects.create(user=user, addon=addon, score=score,
                               note_key=event)
            cls.get_key(invalidate=True)
            user_log.info(
                (u'Awarding %s points to user %s for "%s" for addon %s' % (
                    score, user, amo.REVIEWED_CHOICES[event], addon.id)
             ).encode('utf-8'))
        return score

    @classmethod
    def award_moderation_points(cls, user, addon, review_id):
        """Awards points to user based on moderated review."""
        event = amo.REVIEWED_ADDON_REVIEW
        if addon.type == amo.ADDON_WEBAPP:
            event = amo.REVIEWED_APP_REVIEW
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

        cache.set(key, val, 0)
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
        cache.set(key, val, 0)
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
        with amo.models.skip_cache():
            val = list(ReviewerScore.objects.raw(sql, [user.id]))
        cache.set(key, val, 0)
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
        with amo.models.skip_cache():
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

        week_ago = datetime.date.today() - datetime.timedelta(days=days)

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
        cache.set(key, val, 0)
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


class EscalationQueue(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)

    class Meta:
        db_table = 'escalation_queue'


class RereviewQueue(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)

    class Meta:
        db_table = 'rereview_queue'

    @classmethod
    def flag(cls, addon, event, message=None):
        cls.objects.get_or_create(addon=addon)
        if message:
            amo.log(event, addon, addon.current_version,
                    details={'comments': message})
        else:
            amo.log(event, addon, addon.current_version)


class RereviewQueueThemeManager(amo.models.ManagerBase):

    def __init__(self, include_deleted=False):
        amo.models.ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_query_set(self):
        qs = super(RereviewQueueThemeManager, self).get_query_set()
        if self.include_deleted:
            return qs
        else:
            return qs.exclude(theme__addon__status=amo.STATUS_DELETED)


class RereviewQueueTheme(amo.models.ModelBase):
    theme = models.ForeignKey(Persona)
    header = models.CharField(max_length=72, blank=True, default='')
    footer = models.CharField(max_length=72, blank=True, default='')

    # Holds whether this reuploaded theme is a duplicate.
    dupe_persona = models.ForeignKey(Persona, null=True,
                                     related_name='dupepersona')

    objects = RereviewQueueThemeManager()
    with_deleted = RereviewQueueThemeManager(include_deleted=True)

    class Meta:
        db_table = 'rereview_queue_theme'

    def __str__(self):
        return str(self.id)

    @property
    def header_path(self):
        return self.theme._image_path(self.header or self.theme.header)

    @property
    def footer_path(self):
        return self.theme._image_path(self.footer or self.theme.footer)

    @property
    def header_url(self):
        return self.theme._image_url(self.header or self.theme.header)

    @property
    def footer_url(self):
        return self.theme._image_url(self.footer or self.theme.footer)


class ThemeLock(amo.models.ModelBase):
    theme = models.OneToOneField('addons.Persona')
    reviewer = UserForeignKey()
    expiry = models.DateTimeField()

    class Meta:
        db_table = 'theme_locks'
