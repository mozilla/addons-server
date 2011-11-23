import logging

from django.conf import settings
from django.db import models

import amo.models


log = logging.getLogger('z.perf')


class PerformanceAppVersions(amo.models.ModelBase):
    """
    Add-on performance appversions.  This table is pretty much the same as
    `appversions` but is separate because we need to push the perf stuff now
    and I'm scared to mess with `appversions` because remora uses it in some
    sensitive places.  If we survive past 2012 and people suddenly have too
    much time on their hands, consider merging the two.
    """

    APP_CHOICES = [('firefox', 'Firefox')]

    app = models.CharField(max_length=255, choices=APP_CHOICES)
    version = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = 'perf_appversions'
        ordering = ('-id',)


class PerformanceOSVersion(amo.models.ModelBase):
    os = models.CharField(max_length=255)
    version = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'perf_osversions'
        ordering = ('-id',)

    def __unicode__(self):
        return self.name or '%s %s' % (self.os, self.version)


class Performance(amo.models.ModelBase):
    """Add-on performance numbers.  A bit denormalized."""
    # Cache storage for all platform perf numbers.
    ALL_PLATFORMS = 'perf:platforms'

    TEST_CHOICES = [('ts', 'Startup Time')]

    addon = models.ForeignKey('addons.Addon', null=True,
                              related_name='performance')
    average = models.FloatField(default=0, db_index=True)
    appversion = models.ForeignKey(PerformanceAppVersions)
    osversion = models.ForeignKey(PerformanceOSVersion)
    test = models.CharField(max_length=50, choices=TEST_CHOICES)

    @staticmethod
    def get_threshold():
        """Percentage of slowness in which to flag the result as bad."""
        return getattr(settings, 'PERF_THRESHOLD', 25) or 25

    def get_baseline(self):
        """Gets the latest baseline startup time per Appversion/OS."""
        try:
            res = (Performance.objects
                   .filter(addon=None, appversion=self.appversion,
                           osversion=self.osversion, test=self.test)
                   .order_by('-created'))[0]
            return res.average
        except IndexError:
            # This shouldn't happen but *surprise* it happened in production
            log.info('Performance.get_baseline(): No baseline for '
                     'app %s version %s os %s version %s'
                     % (self.appversion.app, self.appversion.version,
                        self.osversion.os, self.osversion.version))
            return self.average

    def startup_is_too_slow(self, baseline=None):
        """Returns True if this result's startup time is slower
        than the allowed threshold.
        """
        if self.test != 'ts':
            log.info('startup_is_too_slow() only applies to startup time, '
                     'not %s' % self.test)
            return False
        if not baseline:
            baseline = self.get_baseline()
        delta = (self.average - baseline) / baseline * 100
        return delta >= self.get_threshold()

    class Meta:
        db_table = 'perf_results'
