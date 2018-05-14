from django.conf import settings
from django.db import models
from django.utils import translation

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.amo.utils import send_mail
from olympia.users.models import UserProfile


class AbuseReport(ModelBase):
    # NULL if the reporter is anonymous.
    reporter = models.ForeignKey(UserProfile, null=True,
                                 blank=True, related_name='abuse_reported')
    ip_address = models.CharField(max_length=255, default='0.0.0.0')
    # An abuse report can be for an addon or a user.
    # If user is non-null then both addon and guid should be null.
    # If user is null then addon should be non-null if guid was in our DB,
    # otherwise addon will be null also.
    # If both addon and user is null guid should be set.
    addon = models.ForeignKey(Addon, null=True, related_name='abuse_reports')
    guid = models.CharField(max_length=255, null=True)
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

        target_url = ('%s%s' % (settings.SITE_URL, self.target.get_url_path())
                      if self.target else 'GUID not in database')
        name = self.target.name if self.target else self.guid
        msg = u'%s reported abuse for %s (%s).\n\n%s' % (
            user_name, name, target_url, self.message)
        send_mail(unicode(self), msg, recipient_list=(settings.ABUSE_EMAIL,))

    @property
    def target(self):
        return self.addon or self.user

    @property
    def type(self):
        with translation.override(settings.LANGUAGE_CODE):
            type_ = (translation.ugettext(amo.ADDON_TYPE[self.addon.type])
                     if self.addon else 'User' if self.user else 'Addon')
        return type_

    def __unicode__(self):
        name = self.target.name if self.target else self.guid
        return u'[%s] Abuse Report for %s' % (self.type, name)


def send_abuse_report(request, obj, message):
    # Only used by legacy frontend
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
