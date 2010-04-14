# -*- coding: utf-8 -*-
from django.db import models

import caching.base

import amo.models
from addons.models import Addon
from applications.models import Application, AppVersion
from translations.fields import TranslatedField, PurifiedField
from users.models import UserProfile

from . import compare


class Version(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='versions')
    license = models.ForeignKey('License', null=True)
    releasenotes = PurifiedField()
    approvalnotes = models.TextField(default='', null=True)
    version = models.CharField(max_length=255, default=0)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions'
        ordering = ['-created', '-modified']

    def __init__(self, *args, **kwargs):
        super(Version, self).__init__(*args, **kwargs)
        self.__dict__.update(compare.version_dict(self.version or ''))

    def __unicode__(self):
        return self.version

    @amo.cached_property
    def compatible_apps(self):
        """Get a mapping of {APP: ApplicationVersion}."""
        apps = {}
        for av in self.applicationsversions_set.select_related(depth=1):
            app_id = av.application.id
            if app_id in amo.APP_IDS:
                apps[amo.APP_IDS[app_id]] = av
        return apps

    # TODO(jbalogh): Do we want names or Platforms?
    @amo.cached_property
    def supported_platforms(self):
        """Get a list of supported platform names."""
        return list(set(amo.PLATFORMS[f.platform_id]
                        for f in self.files.all()))

    @amo.cached_property
    def has_files(self):
        return bool(self.files.count())

    @amo.cached_property
    def is_unreviewed(self):
        return bool(self.files.filter(status=amo.STATUS_UNREVIEWED))


class License(amo.models.ModelBase):
    """
    Custom as well as built-in licenses.
    A name of -1 indicates a custom license, all names >= 0 are built-in.
    Built-in licenses are defined in amo.__init__
    """

    _name_field = models.IntegerField(null=False,
                                      default=amo.LICENSE_CUSTOM.id,
                                      db_column='name')
    _custom_text = TranslatedField(db_column='text')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'licenses'

    def __unicode__(self):
        return self.name

    @property
    def license_type(self):
        return amo.LICENSE_IDS.get(self._name_field, amo.LICENSE_CUSTOM)

    @license_type.setter
    def license_type(self, license):
        assert license in amo.LICENSES
        self._name_field = license.id

    @property
    def is_custom(self):
        """is this a custom, not built-in, license?"""
        return self.license_type.id == amo.LICENSE_CUSTOM.id

    @property
    def name(self):
        return self.license_type.name

    @property
    def text(self):
        if self.is_custom:
            return self._custom_text
        else:
            return self.license_type.text()

    @text.setter
    def text(self, value):
        if value:
            self.license_type = amo.LICENSE_CUSTOM
        self._custom_text = value

    @property
    def url(self):
        return self.license_type.url


class VersionComment(amo.models.ModelBase):
    """Editor comments for version discussion threads."""
    version = models.ForeignKey(Version)
    user = models.ForeignKey(UserProfile)
    reply_to = models.ForeignKey(Version, related_name="reply_to", null=True)
    subject = models.CharField(max_length=1000)
    comment = models.TextField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versioncomments'


class VersionSummary(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    version = models.ForeignKey(Version)
    application = models.ForeignKey(Application)
    min = models.IntegerField(null=True)
    max = models.IntegerField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions_summary'


class ApplicationsVersions(caching.base.CachingMixin, models.Model):

    application = models.ForeignKey(Application)
    version = models.ForeignKey(Version)
    min = models.ForeignKey(AppVersion, db_column='min',
        related_name='min_set')
    max = models.ForeignKey(AppVersion, db_column='max',
        related_name='max_set')

    objects = caching.base.CachingManager()

    class Meta:
        db_table = u'applications_versions'
        unique_together = (("application", "version"),)

    def __unicode__(self):
        return u'%s: %s - %s' % (self.application, self.min, self.max)
