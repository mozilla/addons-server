from django import test
from django.conf import settings
from django.core import management
from django.db.models import loading
from django.utils.encoding import smart_unicode as unicode

from nose.tools import eq_


class ExtraAppTestCase(test.TestCase):
    extra_apps = []

    @classmethod
    def setup_class(cls):
        for app in cls.extra_apps:
            settings.INSTALLED_APPS += (app,)
            loading.load_app(app)

        management.call_command('syncdb', verbosity=0, interactive=False)

    @classmethod
    def teardown_class(cls):
        # Remove the apps from extra_apps.
        for app_label in cls.extra_apps:
            app_name = app_label.split('.')[-1]
            app = loading.cache.get_app(app_name)
            del loading.cache.app_models[app_name]
            del loading.cache.app_store[app]

        apps = set(settings.INSTALLED_APPS).difference(cls.extra_apps)
        settings.INSTALLED_APPS = tuple(apps)


# Comparisons

def locale_eq(a, b):
    eq_(a.lower(), b.lower())


def trans_eq(translation, string, locale=None):
    eq_(unicode(translation), string)
    if locale:
        locale_eq(translation.locale, locale)
