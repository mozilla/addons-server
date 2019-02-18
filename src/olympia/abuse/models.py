from django.conf import settings
from django.db import models
from django.utils import translation
from django.utils.encoding import python_2_unicode_compatible

import six

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.amo.utils import send_mail
from olympia.users.models import UserProfile


@python_2_unicode_compatible
class AbuseReport(ModelBase):
    # Note: those choices don't need to be translated for now, the
    # human-readable values are only exposed in the admin. The values will be
    # updated once they are finalized in the PRD.
    ADDON_SIGNATURE_CHOICES = (
        (None, 'None'),
    )
    REASON_CHOICES = (
        (None, 'None'),
        (1, 'Malware'),
        (2, 'Spam / Advertising'),
        (3, 'Search takeover'),
        (4, 'New tab takeover'),
        (5, 'Breaks websites'),
        (6, 'Offensive'),
        (7, 'Doesn\'t match description'),
        (8, 'Doesn\'t work'),
    )
    REASON_CHOICES_API = {
        None: None,
        1: 'malware',
        2: 'spam_or_advertising',
        3: 'search_takeover',
        4: 'new_tab_takeover',
        5: 'breaks_websites',
        6: 'offensive',
        7: 'does_not_match_description',
        8: 'does_not_work',
    }
    ADDON_INSTALL_METHOD_CHOICES = (
        (None, 'None'),
    )
    ADDON_INSTALL_ENTRY_POINTS_CHOICES = (
        (None, 'None'),
    )

    # NULL if the reporter is anonymous.
    reporter = models.ForeignKey(
        UserProfile, null=True, blank=True, related_name='abuse_reported',
        on_delete=models.SET_NULL)
    ip_address = models.CharField(max_length=255, default='0.0.0.0')
    # An abuse report can be for an addon or a user.
    # If user is non-null then both addon and guid should be null.
    # If user is null then addon should be non-null if guid was in our DB,
    # otherwise addon will be null also.
    # If both addon and user is null guid should be set.
    addon = models.ForeignKey(
        Addon, null=True, related_name='abuse_reports',
        on_delete=models.CASCADE)
    guid = models.CharField(max_length=255, null=True)
    user = models.ForeignKey(
        UserProfile, null=True, related_name='abuse_reports',
        on_delete=models.SET_NULL)
    message = models.TextField()

    # Extra optional fields for more information, giving some context that is
    # meant to be extracted automatically by the client (i.e. Firefox) and
    # submitted via the API.
    client_id = models.CharField(
        default=None, max_length=64, blank=True, null=True)
    addon_name = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    addon_summary = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    addon_version = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    addon_signature = models.PositiveSmallIntegerField(
        default=None, choices=ADDON_SIGNATURE_CHOICES, blank=True, null=True)
    application = models.PositiveSmallIntegerField(
        default=amo.FIREFOX.id, choices=amo.APPS_CHOICES, blank=True,
        null=True)
    application_version = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    application_locale = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    operating_system = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    operating_system_version = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    install_date = models.DateTimeField(
        default=None, blank=True, null=True)
    reason = models.PositiveSmallIntegerField(
        default=None, choices=REASON_CHOICES, blank=True, null=True)
    addon_install_origin = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    addon_install_method = models.PositiveSmallIntegerField(
        default=None, choices=ADDON_INSTALL_METHOD_CHOICES, blank=True,
        null=True)
    addon_install_entry_point = models.PositiveSmallIntegerField(
        default=None, choices=ADDON_INSTALL_ENTRY_POINTS_CHOICES, blank=True,
        null=True)

    class Meta:
        db_table = 'abuse_reports'

    def send(self):
        if self.reporter:
            user_name = '%s (%s)' % (self.reporter.name, self.reporter.email)
        else:
            user_name = 'An anonymous user'

        target_url = ('%s%s' % (settings.SITE_URL, self.target.get_url_path())
                      if self.target else 'GUID not in database')
        name = self.target.name if self.target else self.guid
        msg = u'%s reported abuse for %s (%s).\n\n%s' % (
            user_name, name, target_url, self.message)
        send_mail(
            six.text_type(self), msg, recipient_list=(settings.ABUSE_EMAIL,))

    def save(self, *args, **kwargs):
        creation = not self.pk
        super(AbuseReport, self).save(*args, **kwargs)
        if creation:
            self.send()

    @property
    def target(self):
        return self.addon or self.user

    @property
    def type(self):
        with translation.override(settings.LANGUAGE_CODE):
            type_ = (translation.ugettext(amo.ADDON_TYPE[self.addon.type])
                     if self.addon else 'User' if self.user else 'Addon')
        return type_

    def __str__(self):
        name = self.target.name if self.target else self.guid
        return u'[%s] Abuse Report for %s' % (self.type, name)


def send_abuse_report(request, obj, message):
    # Only used by legacy frontend
    report = AbuseReport(ip_address=request.META.get('REMOTE_ADDR'),
                         message=message)
    if request.user.is_authenticated:
        report.reporter = request.user
    if isinstance(obj, Addon):
        report.addon = obj
    elif isinstance(obj, UserProfile):
        report.user = obj
    report.save()
