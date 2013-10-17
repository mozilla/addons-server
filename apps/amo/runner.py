from django.conf import settings
from django.db.models import loading

from test_utils.runner import RadicalTestSuiteRunner


class RadicalTestSuiteRunnerWithExtraApps(RadicalTestSuiteRunner):
    def setup_test_environment(self, **kwargs):
        rval = super(RadicalTestSuiteRunnerWithExtraApps,
                     self).setup_test_environment(**kwargs)
        extra_apps = getattr(settings, 'TEST_INSTALLED_APPS')
        if extra_apps:
            installed_apps = getattr(settings, 'INSTALLED_APPS')
            setattr(settings, 'INSTALLED_APPS', installed_apps + extra_apps)
            loading.cache.loaded = False
        return rval
