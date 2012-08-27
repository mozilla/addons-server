import copy
import datetime

import waffle

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Sum
from django.template import Context, loader
from django.utils.datastructures import SortedDict

import amo
import amo.models
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import cache_ns_key, send_mail
from addons.models import Addon
from editors.sql_model import RawSQLModel
from translations.fields import TranslatedField
from users.models import UserProfile
from versions.models import version_uploaded

import commonware.log


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
        items = (EventLog.objects.values('added', 'created')
                                 .filter(type='admin',
                                         action='group_addmember',
                                         changed_id=2)
                                 .order_by('-created')[:5])

        users = UserProfile.objects.filter(id__in=[i['added'] for i in items])
        names = dict((u.id, u.display_name) for u in users)

        return [dict(display_name=names[int(i['added'])], **i) for i in items]


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
    _no_restart = models.CharField(max_length=255)
    _jetpack_versions = models.CharField(max_length=255)
    _latest_versions = models.CharField(max_length=255)
    _latest_version_ids = models.CharField(max_length=255)
    _file_platform_ids = models.CharField(max_length=255)
    _file_platform_vers = models.CharField(max_length=255)
    _info_request_vers = models.CharField(max_length=255)
    _editor_comment_vers = models.CharField(max_length=255)
    _application_ids = models.CharField(max_length=255)
    waiting_time_days = models.IntegerField()
    waiting_time_hours = models.IntegerField()
    waiting_time_min = models.IntegerField()
    is_version_specific = False
    _latest_version_id = None

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
                ('_latest_version_ids', """GROUP_CONCAT(versions.id
                                           ORDER BY versions.created DESC)"""),
                ('_latest_versions', """GROUP_CONCAT(versions.version
                                        ORDER BY versions.created
                                        DESC SEPARATOR '&&&&')"""),
                ('_editor_comment_vers', """GROUP_CONCAT(DISTINCT CONCAT(CONCAT(
                                            versions.has_editor_comment, '-'),
                                            versions.id))"""),
                ('_info_request_vers', """GROUP_CONCAT(DISTINCT CONCAT(CONCAT(
                                          versions.has_info_request, '-'),
                                          versions.id))"""),
                ('_file_platform_vers', """GROUP_CONCAT(DISTINCT CONCAT(CONCAT(
                                           files.platform_id, '-'),
                                           files.version_id))"""),
                ('_file_platform_ids', """GROUP_CONCAT(DISTINCT
                                          files.platform_id)"""),
                ('_jetpack_versions', """GROUP_CONCAT(DISTINCT
                                         files.jetpack_version)"""),
                ('_no_restart', """GROUP_CONCAT(DISTINCT files.no_restart)"""),
                ('_application_ids', """GROUP_CONCAT(DISTINCT
                                        apps.application_id)"""),
            ]),
            'from': [
                'files',
                'JOIN versions ON (files.version_id = versions.id)',
                'JOIN addons ON (versions.addon_id = addons.id)',
                """JOIN files AS version_files ON (
                            version_files.version_id = versions.id)""",
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
    def latest_version(self):
        return self._explode_concat(self._latest_versions, sep='&&&&',
                                    cast=unicode)[0]

    @property
    def latest_version_id(self):
        if not self._latest_version_id:
            ids = self._explode_concat(self._latest_version_ids)
            self._latest_version_id = ids[0]
        return self._latest_version_id

    @property
    def is_restartless(self):
        return any(self._explode_concat(self._no_restart))

    @property
    def is_jetpack(self):
        return bool(self._jetpack_versions)

    @property
    def is_premium(self):
        return self.premium_type in amo.ADDON_PREMIUMS

    @property
    def file_platform_vers(self):
        return self._explode_concat(self._file_platform_vers, cast=str)

    @property
    def has_info_request(self):
        return self.for_latest_version(self._info_request_vers)

    @property
    def has_editor_comment(self):
        return self.for_latest_version(self._editor_comment_vers)

    @property
    def file_platform_ids(self):
        return self._explode_concat(self._file_platform_ids)

    @property
    def application_ids(self):
        return self._explode_concat(self._application_ids)

    def for_latest_version(self, vals, cast=int, default=0):
        split = self._explode_concat(vals, cast=str)
        for s in split:
            val, version_id = s.split('-')
            if int(version_id) == self.latest_version_id:
                return cast(val)
        return default


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
                                            amo.STATUS_LITE,
                                            amo.STATUS_UNREVIEWED,
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
            'url': absolutify(reverse('addons.detail', args=[self.addon.pk])),
            'number': version.version,
            'review': absolutify(reverse('editors.review',
                                         args=[self.addon.pk])),
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
    def get_event_by_type(cls, addon, review_type=None):
        if addon.type == amo.ADDON_EXTENSION:
            # Special case for addons depending on review_type.
            if review_type == 'nominated':
                return amo.REVIEWED_ADDON_FULL
            elif review_type == 'preliminary':
                return amo.REVIEWED_ADDON_PRELIM
            else:
                return amo.REVIEWED_ADDON_UPDATED
        elif addon.type == amo.ADDON_DICT:
            return amo.REVIEWED_DICT
        elif addon.type in [amo.ADDON_LPAPP, amo.ADDON_LPADDON]:
            return amo.REVIEWED_LP
        elif addon.type == amo.ADDON_PERSONA:
            return amo.REVIEWED_PERSONA
        elif addon.type == amo.ADDON_SEARCH:
            return amo.REVIEWED_SEARCH
        elif addon.type == amo.ADDON_THEME:
            return amo.REVIEWED_THEME
        elif addon.type == amo.ADDON_WEBAPP:
            return amo.REVIEWED_WEBAPP
        else:
            return None

    @classmethod
    def award_points(cls, user, addon, event):
        """Awards points to user based on an event.

        `event` is one of the `REVIEWED_` keys in constants.

        """
        if not waffle.switch_is_active('reviewer-incentive-points'):
            return
        score = amo.REVIEWED_SCORES.get(event)
        if score:
            cls.objects.create(user=user, addon=addon, score=score,
                               note_key=event)
            cls.get_key(invalidate=True)
            user_log.info(u'Awarding %s points to user %s for "%s" for addon'
                           '%s' % (score, user, amo.REVIEWED_CHOICES[event],
                                   addon.id))

    @classmethod
    def get_total(cls, user):
        """Returns total points by user."""
        key = cls.get_key('get_total:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        val = (ReviewerScore.uncached.filter(user=user)
                                     .aggregate(total=Sum('score'))
                                     .values())[0]
        if val is None:
            val = 0

        cache.set(key, val, 0)
        return val

    @classmethod
    def get_recent(cls, user, limit=5):
        """Returns most recent ReviewerScore records."""
        key = cls.get_key('get_recent:%s' % user.id)
        val = cache.get(key)
        if val is not None:
            return val

        val = list(ReviewerScore.uncached.filter(user=user)[:limit])
        cache.set(key, val, 0)
        return val

    @classmethod
    def get_leaderboards(cls, user, days=7):
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

        # I'd normally use Django's ORM aggregation but bug 17144 scared me
        # away.
        leader_top = []
        leader_near = []
        in_leaderboard = (ReviewerScore.uncached.filter(created__gte=week_ago,
                                                        user=user)
                                                .exists())

        sql = """SELECT *, SUM(`reviewer_scores`.`score`) AS `total`
                 FROM `reviewer_scores`
                 WHERE `created` >= %s
                 GROUP BY `user_id`
                 ORDER BY `total` DESC"""

        rank = 0
        if not in_leaderboard:
            sql += ' LIMIT 5'  # Top 5 if not in leaderboard.
            leader_top = list(ReviewerScore.uncached.raw(sql, [week_ago]))
        else:
            scores = list(ReviewerScore.uncached.raw(sql, [week_ago]))
            for i, score in enumerate(scores, 1):
                score.rank = i
                if user.id == score.user_id:
                    rank = i

            if rank <= 5:  # User is in top 5, show top 5.
                leader_top = scores[:5]
            else:
                leader_top = scores[:3]
                leader_near = [scores[rank - 2], scores[rank - 1]]
                try:
                    leader_near.append(scores[rank])
                except IndexError:
                    pass  # User is last on the leaderboard.

        val = {
            'leader_top': leader_top,
            'leader_near': leader_near,
            'user_rank': rank,
        }
        cache.set(key, val, 0)
        return val


class EscalationQueue(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)

    class Meta:
        db_table = 'escalation_queue'
