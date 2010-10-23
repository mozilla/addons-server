# -*- coding: utf-8 -*-
import itertools

from django.db import models

import caching.base

from amo.urlresolvers import reverse
import amo.models
from applications.models import Application, AppVersion
from files.models import File
from translations.fields import (TranslatedField, PurifiedField,
                                 LinkifiedField)
from users.models import UserProfile

from . import compare


class Version(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='versions')
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

    def license_url(self):
        return reverse('addons.license', args=[self.addon_id, self.version])

    def flush_urls(self):
        return self.addon.flush_urls()

    @amo.cached_property(writable=True)
    def compatible_apps(self):
        """Get a mapping of {APP: ApplicationVersion}."""
        avs = self.apps.select_related(depth=1)
        return self._compat_map(avs)

    @amo.cached_property(writable=True)
    def all_files(self):
        """Shortcut for list(self.files.all()).  Heavily cached."""
        return list(self.files.all())

    # TODO(jbalogh): Do we want names or Platforms?
    @amo.cached_property
    def supported_platforms(self):
        """Get a list of supported platform names."""
        return list(set(amo.PLATFORMS[f.platform_id]
                        for f in self.all_files))

    @amo.cached_property
    def has_files(self):
        return bool(self.all_files)

    @amo.cached_property
    def is_unreviewed(self):
        return filter(lambda f: f.status in amo.UNREVIEWED_STATUSES,
                      self.all_files)

    @amo.cached_property
    def is_beta(self):
        return filter(lambda f: f.status == amo.STATUS_BETA,
                      self.all_files)

    @classmethod
    def _compat_map(cls, avs):
        apps = {}
        for av in avs:
            app_id = av.application_id
            if app_id in amo.APP_IDS:
                apps[amo.APP_IDS[app_id]] = av
        return apps

    @classmethod
    def transformer(cls, versions):
        """Attach all the compatible apps and files to the versions."""
        if not versions:
            return

        avs = (ApplicationsVersions.objects.filter(version__in=versions)
               .select_related(depth=1).order_by('version__id').no_cache())
        files = (File.objects.filter(version__in=versions)
                 .order_by('version__id').select_related('version').no_cache())

        def rollup(xs):
            groups = itertools.groupby(xs, key=lambda x: x.version_id)
            return dict((k, list(vs)) for k, vs in groups)

        av_dict, file_dict = rollup(avs), rollup(files)

        for version in versions:
            v_id = version.id
            version.compatible_apps = cls._compat_map(av_dict.get(v_id, []))
            version.all_files = file_dict.get(v_id, [])


class LicenseManager(amo.models.ManagerBase):

    def builtins(self):
        return self.filter(builtin__gt=0).order_by('builtin')


class License(amo.models.ModelBase):
    OTHER = 0

    name = TranslatedField(db_column='name')
    url = models.URLField(null=True)
    builtin = models.PositiveIntegerField(default=OTHER)
    text = LinkifiedField()
    on_form = models.BooleanField(default=False,
        help_text='Is this a license choice in the devhub?')
    some_rights = models.BooleanField(default=False,
        help_text='Show "Some Rights Reserved" instead of the license name?')
    icons = models.CharField(max_length=255, null=True,
        help_text='Space-separated list of icon identifiers.')

    objects = LicenseManager()

    class Meta:
        db_table = 'licenses'

    def __unicode__(self):
        return '%s %s' % (self.id, self.name)


class VersionComment(amo.models.ModelBase):
    """Editor comments for version discussion threads."""
    version = models.ForeignKey(Version)
    user = models.ForeignKey(UserProfile)
    reply_to = models.ForeignKey(Version, related_name="reply_to",
                                 db_column='reply_to', null=True)
    subject = models.CharField(max_length=1000)
    comment = models.TextField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versioncomments'


class VersionSummary(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon')
    version = models.ForeignKey(Version)
    application = models.ForeignKey(Application)
    min = models.IntegerField(null=True)
    max = models.IntegerField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'versions_summary'


class ApplicationsVersions(caching.base.CachingMixin, models.Model):

    application = models.ForeignKey(Application)
    version = models.ForeignKey(Version, related_name='apps')
    min = models.ForeignKey(AppVersion, db_column='min',
        related_name='min_set')
    max = models.ForeignKey(AppVersion, db_column='max',
        related_name='max_set')

    objects = caching.base.CachingManager()

    class Meta:
        db_table = u'applications_versions'
        unique_together = (("application", "version"),)

    def __unicode__(self):
        return u'%s %s - %s' % (self.application, self.min, self.max)
