import collections

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

    def get_compatible_apps(self):
        """
        Looks at the current version and gives us a list of namedtuples of
        Application, Min and Max version.
        """
        compat_list = []

        Compatibility = collections.namedtuple(
                'Compatibility', 'application max min')
        avs = self.applicationsversions_set.select_related().all()

        [compat_list.append(Compatibility(
            av.application, av.max.version, av.min.version)) for av in avs]

        return compat_list

    def get_supported_platforms(self):
        """
        Looks at the current version and gives us a list of supported versions.
        """
        platforms = []
        [platforms.append(file.platform.name) for file in
                self.files.all()]

        return list(set(platforms))


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
