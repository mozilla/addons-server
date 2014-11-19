from django.conf import settings
from django.db.models import loading

import django_nose


class TestRunner(django_nose.NoseTestSuiteRunner):
    def setup_test_environment(self, **kwargs):
        rval = super(TestRunner, self).setup_test_environment(**kwargs)
        extra_apps = getattr(settings, 'TEST_INSTALLED_APPS')
        if extra_apps:
            installed_apps = getattr(settings, 'INSTALLED_APPS')
            setattr(settings, 'INSTALLED_APPS', installed_apps + extra_apps)
            loading.cache.loaded = False
        return rval
