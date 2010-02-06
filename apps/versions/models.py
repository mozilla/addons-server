from django.db import models

import caching.base

import amo.models
from addons.models import Addon
from applications.models import Application, AppVersion
from translations.fields import TranslatedField
from users.models import UserProfile


class Version(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='versions')
    license = models.ForeignKey('License', null=True)
    releasenotes = TranslatedField()
    approvalnotes = models.TextField()
    version = models.CharField(max_length=255, default=0)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions'
        ordering = ['-created']

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
        return list(set(f.platform.name for f in self.files.all()))


class License(amo.models.ModelBase):
    rating = models.SmallIntegerField(default=-1)
    text = TranslatedField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'licenses'


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
