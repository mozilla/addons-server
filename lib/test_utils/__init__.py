from django import test
from django.conf import settings
from django.core import management
from django.db.models import loading
from django.utils.encoding import smart_unicode as unicode

from nose.tools import eq_


class ExtraAppTestCase(test.TestCase):
    extra_apps = []

    def _pre_setup(self):
        for app in self.extra_apps:
            settings.INSTALLED_APPS += (app,)
            loading.load_app(app)

        management.call_command('syncdb', verbosity=0, interactive=False)

        super(ExtraAppTestCase, self)._pre_setup()

    def _post_teardown(self):
        # Remove the apps from extra_apps.
        apps = set(settings.INSTALLED_APPS).difference(self.extra_apps)
        settings.INSTALLED_APPS = tuple(apps)

        super(ExtraAppTestCase, self)._post_teardown()
        """
        for app_label in self.extra_apps:
            app = loading.cache.get_app(app_label)
            for model in loading.cache.get_models(app):
                del cache.app_store[model]
        """


# Comparisons

def locale_eq(a, b):
    eq_(a.lower(), b.lower())


def trans_eq(translation, string, locale=None):
    eq_(unicode(translation), string)
    if locale:
        locale_eq(translation.locale, locale)
