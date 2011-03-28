import copy

from django.conf import settings
from django.db import models
from django.template import Context, loader
from django.utils.datastructures import SortedDict

import amo
import amo.models
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import send_mail
from addons.models import Addon
from editors.sql_model import RawSQLModel
from translations.fields import TranslatedField
from tower import ugettext as _
from users.models import UserProfile
from versions.models import Version

import commonware.log


user_log = commonware.log.getLogger('z.users')


class CannedResponse(amo.models.ModelBase):

    name = TranslatedField()
    response = TranslatedField()
    sort_group = models.CharField(max_length=255)

    class Meta:
        db_table = 'cannedresponses'

    def __unicode__(self):
        return unicode(self.name)


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
    addon_status = models.IntegerField()
    addon_type_id = models.IntegerField()
    admin_review = models.BooleanField()
    is_site_specific = models.BooleanField()
    external_software = models.BooleanField()
    binary = models.BooleanField()
    _latest_versions = models.CharField(max_length=255)
    _latest_version_ids = models.CharField(max_length=255)
    _file_platform_ids = models.CharField(max_length=255)
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
                ('admin_review', 'addons.adminreview'),
                ('is_site_specific', 'addons.sitespecific'),
                ('external_software', 'addons.externalsoftware'),
                ('binary', 'addons.binary'),
                ('_latest_version_ids', """GROUP_CONCAT(versions.id
                                           ORDER BY versions.created DESC)"""),
                ('_latest_versions', """GROUP_CONCAT(versions.version
                                        ORDER BY versions.created
                                                 DESC SEPARATOR '&&&&')"""),
                ('_file_platform_ids', """GROUP_CONCAT(DISTINCT
                                                       files.platform_id)"""),
                ('_application_ids', """GROUP_CONCAT(DISTINCT
                                                     apps.application_id)"""),
            ]),
            'from': [
                'files',
                'JOIN versions ON (files.version_id = versions.id)',
                'JOIN addons ON (versions.addon_id = addons.id)',
                """LEFT JOIN applications_versions as apps
                            ON versions.id = apps.version_id""",
                """JOIN translations AS tr ON (
                            tr.id = addons.name
                            AND tr.locale = addons.defaultlocale)"""
            ],
            'where': [],
            'group_by': 'id'}

    @property
    def latest_version(self):
        return self._explode_concat(self._latest_versions, sep='&&&&',
                                    cast=unicode)[0]

    @property
    def latest_version_id(self):
        return self._explode_concat(self._latest_version_ids)[0]

    @property
    def file_platform_ids(self):
        return self._explode_concat(self._file_platform_ids)

    @property
    def application_ids(self):
        return self._explode_concat(self._application_ids)


class ViewFullReviewQueue(ViewQueue):

    def base_query(self):
        q = super(ViewFullReviewQueue, self).base_query()
        q['select'].update({
            'waiting_time_days':
                'TIMESTAMPDIFF(DAY, versions.nomination, NOW())',
            'waiting_time_hours':
                'TIMESTAMPDIFF(HOUR, versions.nomination, NOW())',
            'waiting_time_min':
                'TIMESTAMPDIFF(MINUTE, versions.nomination, NOW())',
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
                'TIMESTAMPDIFF(DAY, MAX(versions.created), NOW())',
            'waiting_time_hours':
                'TIMESTAMPDIFF(HOUR, MAX(versions.created), NOW())',
            'waiting_time_min':
                'TIMESTAMPDIFF(MINUTE, MAX(versions.created), NOW())',
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
            'review': absolutify(reverse('editors.review', args=[version.pk])),
            'SITE_URL': settings.SITE_URL,
        })
        #L10N: addon.name
        subject = _('Mozilla Add-ons: %s Updated') % self.addon.name
        template = loader.get_template('editors/emails/notify_update.ltxt')
        send_mail(subject, template.render(Context(context)),
                  recipient_list=[self.user.email],
                  from_email=settings.EDITORS_EMAIL,
                  use_blacklist=False)


def send_notifications(sender, instance, **kw):
    if kw.get('raw') or not kw.get('created'):
        return

    subscribers = instance.addon.editorsubscription_set.all()
    if not subscribers:
        return

    for subscriber in subscribers:
        subscriber.send_notification(instance)
        subscriber.delete()


models.signals.post_save.connect(send_notifications, sender=Version,
                                 dispatch_uid='version_send_notifications')
