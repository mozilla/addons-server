import logging

from django.conf import settings
from django.db import models

import amo.models
import amo.utils
from addons.models import Addon
from users.models import UserProfile


log = logging.getLogger('z.abuse')


class AbuseReport(amo.models.ModelBase):
    # NULL if the reporter is anonymous.
    reporter = models.ForeignKey(UserProfile, null=True,
                                 related_name='abuse_reported')
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
            user_name = 'An anonymous user'
        subject = 'Abuse Report for %s' % obj.name
        msg = u'%s reported abuse for %s (%s%s).\n\n%s' % (
            user_name, obj.name, settings.SITE_URL, obj.get_url_path(),
            self.message)
        amo.utils.send_mail(subject, msg, recipient_list=(settings.FLIGTAR,))


def send_abuse_report(request, obj, message):
    report = AbuseReport(ip_address=request.META.get('REMOTE_ADDR'),
                         message=message)
    if request.user.is_authenticated():
        report.reporter = request.amo_user
    if isinstance(obj, Addon):
        report.addon = obj
    elif isinstance(obj, UserProfile):
        report.user = obj
    report.save()
    report.send()
