from django.conf import settings
from django.db import models
from django.utils.translation import gettext

from olympia import amo
from olympia.amo.models import ModelBase
from olympia.amo.utils import send_mail, no_translation
from olympia.addons.models import Addon
from olympia.users.models import UserProfile


class AbuseReport(ModelBase):
    # NULL if the reporter is anonymous.
    reporter = models.ForeignKey(UserProfile, null=True,
                                 blank=True, related_name='abuse_reported')
    ip_address = models.CharField(max_length=255, default='0.0.0.0')
    # An abuse report can be for an addon or a user. Only one of these should
    # be null.
    addon = models.ForeignKey(Addon, null=True, related_name='abuse_reports')
    user = models.ForeignKey(UserProfile, null=True,
                             related_name='abuse_reports')
    message = models.TextField()

    class Meta:
        db_table = 'abuse_reports'

    def send(self):
        obj = self.addon or self.user
        if self.reporter:
            user_name = '%s (%s)' % (self.reporter.name, self.reporter.email)
        else:
            user_name = 'An anonymous coward'

        with no_translation():
            type_ = (gettext(amo.ADDON_TYPE[self.addon.type])
                     if self.addon else 'User')

        subject = u'[%s] Abuse Report for %s' % (type_, obj.name)
        msg = u'%s reported abuse for %s (%s%s).\n\n%s' % (
            user_name, obj.name, settings.SITE_URL, obj.get_url_path(),
            self.message)
        send_mail(subject, msg,
                  recipient_list=(settings.ABUSE_EMAIL,))

    @classmethod
    def recent_high_abuse_reports(cls, threshold, period, addon_id=None,
                                  addon_type=None):
        """
        Returns AbuseReport objects for the given threshold over the given time
        period (in days). Filters by addon_id or addon_type if provided.

        E.g. Greater than 5 abuse reports for all addons in the past 7 days.
        """
        abuse_sql = ['''
            SELECT `abuse_reports`.*,
                   COUNT(`abuse_reports`.`addon_id`) AS `num_reports`
            FROM `abuse_reports`
            INNER JOIN `addons` ON (`abuse_reports`.`addon_id` = `addons`.`id`)
            WHERE `abuse_reports`.`created` >= %s ''']
        params = [period]
        if addon_id:
            abuse_sql.append('AND `addons`.`id` = %s ')
            params.append(addon_id)
        elif addon_type and addon_type in amo.ADDON_TYPES:
            abuse_sql.append('AND `addons`.`addontype_id` = %s ')
            params.append(addon_type)
        abuse_sql.append('GROUP BY addon_id HAVING num_reports > %s')
        params.append(threshold)

        return list(cls.objects.raw(''.join(abuse_sql), params))


def send_abuse_report(request, obj, message):
    report = AbuseReport(ip_address=request.META.get('REMOTE_ADDR'),
                         message=message)
    if request.user.is_authenticated():
        report.reporter = request.user
    if isinstance(obj, Addon):
        report.addon = obj
    elif isinstance(obj, UserProfile):
        report.user = obj
    report.save()
    report.send()
