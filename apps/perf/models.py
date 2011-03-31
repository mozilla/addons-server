from django.db import models

import amo.models


class PerformanceAppVersions(amo.models.ModelBase):
    """
    Add-on performance appversions.  This table is pretty much the same as
    `appversions` but is separate because we need to push the perf stuff now
    and I'm scared to mess with `appversions` because remora uses it in some
    sensitive places.  If we survive past 2012 and people suddenly have too
    much time on their hands, consider merging the two.
    """

    APP_CHOICES = [('fx', 'Firefox')]

    app = models.CharField(max_length=255, choices=APP_CHOICES)
    version = models.CharField(max_length=255, db_index=True)

    class Meta:
        db_table = 'perf_appversions'


class PerformanceOSVersion(amo.models.ModelBase):
    os = models.CharField(max_length=255)
    version = models.CharField(max_length=255)
    name = models.CharField(max_length=255)

    class Meta:
        db_table = 'perf_osversions'

    def __unicode__(self):
        return self.name or '%s %s' % (self.os, self.version)


class Performance(amo.models.ModelBase):
    """Add-on performance numbers.  A bit denormalized."""
    # Cache storage for all platform perf numbers.
    ALL_PLATFORMS = 'perf:platforms'

    TEST_CHOICES = [('ts', 'Startup Time')]

    addon = models.ForeignKey('addons.Addon', null=True)
    average = models.FloatField(default=0, db_index=True)
    appversion = models.ForeignKey(PerformanceAppVersions)
    osversion = models.ForeignKey(PerformanceOSVersion)
    test = models.CharField(max_length=50, choices=TEST_CHOICES)

    class Meta:
        db_table = 'perf_results'
