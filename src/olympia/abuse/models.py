from django import forms
from django.conf import settings
from django.contrib.gis.geoip2 import GeoIP2, GeoIP2Exception
from django.core.validators import validate_ipv46_address
from django.db import models
from django.utils import translation

from extended_choices import Choices
from geoip2.errors import GeoIP2Error

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ManagerBase, ModelBase
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


class AbuseReport(ModelBase):
    # Note: those choices don't need to be translated for now, the
    # human-readable values are only exposed in the admin.
    ADDON_SIGNATURES = APIChoicesWithNone(
        ('CURATED_AND_PARTNER', 1, 'Curated and partner'),
        ('CURATED', 2, 'Curated'),
        ('PARTNER', 3, 'Partner'),
        ('NON_CURATED', 4, 'Non-curated'),
        ('UNSIGNED', 5, 'Unsigned'),
        ('BROKEN', 6, 'Broken'),
        ('UNKNOWN', 7, 'Unknown'),
        ('MISSING', 8, 'Missing'),
        ('PRELIMINARY', 9, 'Preliminary'),
        ('SIGNED', 10, 'Signed'),
        ('SYSTEM', 11, 'System'),
        ('PRIVILEGED', 12, 'Privileged'),
    )
    REASONS = APIChoicesWithNone(
        ('DAMAGE', 1, 'Damages computer and/or data'),
        ('SPAM', 2, 'Creates spam or advertising'),
        ('SETTINGS', 3, 'Changes search / homepage / new tab page '
                        'without informing user'),
        # `4` was previously 'New tab takeover' but has been merged into the
        # previous one. We avoid re-using the value.
        ('BROKEN', 5, "Doesn’t work, breaks websites, or slows Firefox down"),
        ('POLICY', 6, 'Hateful, violent, or illegal content'),
        ('DECEPTIVE', 7, "Pretends to be something it’s not"),
        # `8` was previously "Doesn't work" but has been merged into the
        # previous one. We avoid re-using the value.
        ('UNWANTED', 9, "Wasn't wanted / impossible to get rid of"),
        # `10` was previously "Other". We avoid re-using the value.
        ('OTHER', 127, 'Other'),
    )

    # https://searchfox.org
    # /mozilla-central/source/toolkit/components/telemetry/Events.yaml#122-131
    # Firefox submits values in lowercase, with '-' and ':' changed to '_'.
    ADDON_INSTALL_METHODS = APIChoicesWithNone(
        ('AMWEBAPI', 1, 'Add-on Manager Web API'),
        ('LINK', 2, 'Direct link'),
        ('INSTALLTRIGGER', 3, 'Install Trigger'),
        ('INSTALL_FROM_FILE', 4, 'From File'),
        ('MANAGEMENT_WEBEXT_API', 5, 'Webext management API'),
        ('DRAG_AND_DROP', 6, 'Drag & Drop'),
        ('SIDELOAD', 7, 'Sideload'),
        # Values between 8 and 13 are obsolete, we use to merge
        # install source and method into addon_install_method before deciding
        # to split the two like Firefox does, so these 6 values are only kept
        # for backwards-compatibility with older reports and older versions of
        # Firefox that still only submit that.
        ('FILE_URL', 8, 'File URL'),
        ('ENTERPRISE_POLICY', 9, 'Enterprise Policy'),
        ('DISTRIBUTION', 10, 'Included in build'),
        ('SYSTEM_ADDON', 11, 'System Add-on'),
        ('TEMPORARY_ADDON', 12, 'Temporary Add-on'),
        ('SYNC', 13, 'Sync'),
        # Back to normal values.
        ('URL', 14, 'URL'),
        # Our own catch-all. The serializer expects it to be called "OTHER".
        ('OTHER', 127, 'Other'),
    )
    ADDON_INSTALL_SOURCES = APIChoicesWithNone(
        ('ABOUT_ADDONS', 1, 'Add-ons Manager'),
        ('ABOUT_DEBUGGING', 2, 'Add-ons Debugging'),
        ('ABOUT_PREFERENCES', 3, 'Preferences'),
        ('AMO', 4, 'AMO'),
        ('APP_PROFILE', 5, 'App Profile'),
        ('DISCO', 6, 'Disco Pane'),
        ('DISTRIBUTION', 7, 'Included in build'),
        ('EXTENSION', 8, 'Extension'),
        ('ENTERPRISE_POLICY', 9, 'Enterprise Policy'),
        ('FILE_URL', 10, 'File URL'),
        ('GMP_PLUGIN', 11, 'GMP Plugin'),
        ('INTERNAL', 12, 'Internal'),
        ('PLUGIN', 13, 'Plugin'),
        ('RTAMO', 14, 'Return to AMO'),
        ('SYNC', 15, 'Sync'),
        ('SYSTEM_ADDON', 16, 'System Add-on'),
        ('TEMPORARY_ADDON', 17, 'Temporary Add-on'),
        ('UNKNOWN', 18, 'Unknown'),
        # Our own catch-all. The serializer expects it to be called "OTHER".
        ('OTHER', 127, 'Other'),
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
    country_code = models.CharField(
        max_length=2, default=None, null=True)
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
    message = models.TextField(blank=True)

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
    addon_install_source = models.PositiveSmallIntegerField(
        default=None, choices=ADDON_INSTALL_SOURCES.choices, blank=True,
        null=True)
    report_entry_point = models.PositiveSmallIntegerField(
        default=None, choices=REPORT_ENTRY_POINTS.choices, blank=True,
        null=True)

    unfiltered = AbuseReportManager(include_deleted=True)
    objects = AbuseReportManager()

    class Meta:
        db_table = 'abuse_reports'
        # See comment in addons/models.py about base_manager_name. It needs to
        # be unfiltered to prevent exceptions when dealing with relations or
        # saving already deleted objects.
        base_manager_name = 'unfiltered'
        indexes = [
            models.Index(fields=('created',), name='created_idx'),
        ]

    @property
    def metadata(self):
        """
        Dict of metadata about this report. Only includes non-null values.
        """
        data = {}
        field_names = (
            'client_id', 'addon_name', 'addon_summary', 'addon_version',
            'addon_signature', 'application', 'application_version',
            'application_locale', 'operating_system',
            'operating_system_version', 'install_date', 'reason',
            'addon_install_origin', 'addon_install_method',
            'report_entry_point'
        )
        for field_name in field_names:
            value = self.__dict__[field_name]
            # Only include values that matter.
            if value is not None:
                field = self._meta.get_field(field_name)
                # If it's a choice field, display the "pretty" version.
                if field.choices:
                    value = getattr(self, 'get_%s_display' % field_name)()
                data[field_name] = value
        return data

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
        with translation.override(settings.LANGUAGE_CODE):
            if self.addon and self.addon.type in amo.ADDON_TYPE:
                type_ = (translation.ugettext(amo.ADDON_TYPE[self.addon.type]))
            elif self.user:
                type_ = 'User'
            else:
                type_ = 'Addon'
        return type_

    def __str__(self):
        name = self.target.name if self.target else self.guid
        return u'[%s] Abuse Report for %s' % (self.type, name)
