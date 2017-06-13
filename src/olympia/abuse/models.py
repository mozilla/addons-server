from django.conf import settings
from django.db import models
from django.utils.translation import ugettext

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
        if self.reporter:
            user_name = '%s (%s)' % (self.reporter.name, self.reporter.email)
        else:
            user_name = 'An anonymous coward'

        msg = u'%s reported abuse for %s (%s%s).\n\n%s' % (
            user_name, self.target.name, settings.SITE_URL,
            self.target.get_url_path(), self.message)
        send_mail(unicode(self), msg,
                  recipient_list=(settings.ABUSE_EMAIL,))

    @property
    def target(self):
        return self.addon or self.user

    @property
    def type(self):
        with no_translation():
            type_ = (ugettext(amo.ADDON_TYPE[self.addon.type])
                     if self.addon else 'User')
        return type_

    def __unicode__(self):
        return u'[%s] Abuse Report for %s' % (self.type, self.target.name)


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
