from django import forms
from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2, GeoIP2Exception
from django.core.validators import validate_ipv46_address
from django.db import models
from django.utils.encoding import python_2_unicode_compatible

import six

from extended_choices import Choices
from geoip2.errors import GeoIP2Error

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ManagerBase, ModelBase
from olympia.amo.utils import send_mail
from olympia.api.utils import APIChoicesWithNone
from olympia.users.models import UserProfile


class AbuseReportManager(ManagerBase):
    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.include_deleted:
            qs = qs.exclude(state=self.model.STATES.DELETED)
        return qs


@python_2_unicode_compatible
class AbuseReport(ModelBase):
    # Note: those choices don't need to be translated for now, the
    # human-readable values are only exposed in the admin.
    ADDON_SIGNATURES = APIChoicesWithNone(
        ('CURATED_AND_PARTNER', 1, 'Curated and partner'),
        ('CURATED', 2, 'Curated'),
        ('PARTNER', 3, 'Partner'),
        ('NON_CURATED', 4, 'Non-curated'),
        ('UNSIGNED', 5, 'Unsigned'),
    )
    REASONS = APIChoicesWithNone(
        ('HARMFUL', 1, 'Damages computer and/or data'),
        ('SPAM_OR_ADVERTISING', 2, 'Creates spam or advertising'),
        ('BROWSER_TAKEOVER', 3, 'Changes search / homepage / new tab page '
                                'without informing user'),
        # `4` was previously 'New tab takeover' but has been merged into the
        # previous one. We avoid re-using the value.
        ('BROKEN', 5, "Doesn’t work, breaks websites, or slows Firefox down"),
        ('OFFENSIVE', 6, 'Hateful, violent, or illegal content'),
        ('DOES_NOT_MATCH_DESCRIPTION', 7, "Pretends to be something it’s not"),
        # `8` was previously "Doesn't work" but has been merged into the
        # previous one. We avoid re-using the value.
        ('UNWANTED', 9, "Wasn't wanted / impossible to get rid of"),
        ('OTHER', 10, 'Other'),
    )

    ADDON_INSTALL_METHODS = APIChoicesWithNone(
        ('AMWEBAPI', 1, 'Add-on Manager Web API'),
        ('LINK', 2, 'Direct link'),
        ('INSTALLTRIGGER', 3, 'Install Trigger'),
        ('INSTALL_FROM_FILE', 4, 'From File'),
        ('MANAGEMENT_WEBEXT_API', 5, 'Webext management API'),
        ('DRAG_AND_DROP', 6, 'Drag & Drop'),
        ('SIDELOAD', 7, 'Sideload'),
    )
    REPORT_ENTRY_POINTS = APIChoicesWithNone(
        ('UNINSTALL', 1, 'Uninstall'),
        ('MENU', 2, 'Menu'),
        ('TOOLBAR_CONTEXT_MENU', 3, 'Toolbar context menu'),
    )
    STATES = Choices(
        ('UNTRIAGED', 1, 'Untriaged'),
        ('VALID', 2, 'Valid'),
        ('SUSPICIOUS', 3, 'Suspicious'),
        ('DELETED', 4, 'Deleted'),
    )

    # NULL if the reporter is anonymous.
    reporter = models.ForeignKey(
        UserProfile, null=True, blank=True, related_name='abuse_reported',
        on_delete=models.SET_NULL)
    country_code = models.CharField(max_length=2, default=None, null=True)
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

    state = models.PositiveSmallIntegerField(
        default=STATES.UNTRIAGED, choices=STATES.choices)

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
        default=None, choices=ADDON_SIGNATURES.choices, blank=True, null=True)
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
        default=None, choices=REASONS.choices, blank=True, null=True)
    addon_install_origin = models.CharField(
        default=None, max_length=255, blank=True, null=True)
    addon_install_method = models.PositiveSmallIntegerField(
        default=None, choices=ADDON_INSTALL_METHODS.choices, blank=True,
        null=True)
    report_entry_point = models.PositiveSmallIntegerField(
        default=None, choices=REPORT_ENTRY_POINTS.choices, blank=True,
        null=True)

    unfiltered = AbuseReportManager(include_deleted=True)
    objects = AbuseReportManager()

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

    def delete(self, *args, **kwargs):
        # AbuseReports are soft-deleted. Note that we keep relations, because
        # the only possible relations are to users and add-ons, which are also
        # soft-deleted.
        return self.update(state=self.STATES.DELETED)

    @classmethod
    def lookup_country_code_from_ip(cls, ip):
        try:
            # Early check to avoid initializing GeoIP2 on invalid addresses
            if not ip:
                raise forms.ValidationError('No IP')
            validate_ipv46_address(ip)
            geoip = GeoIP2()
            value = geoip.country_code(ip)
        # Annoyingly, we have to catch both django's GeoIP2Exception (setup
        # issue) and geoip2's GeoIP2Error (lookup issue)
        except (forms.ValidationError, GeoIP2Exception, GeoIP2Error):
            value = ''
        return value

    @property
    def target(self):
        return self.addon or self.user

    @property
    def type(self):
        return 'User' if self.user else 'Addon'

    def __str__(self):
        name = self.target.name if self.target else self.guid
        return u'[%s] Abuse Report for %s' % (self.type, name)
