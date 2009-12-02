"""
Borrowed from: http://code.google.com/p/django-localeurl

Note: didn't make sense to use localeurl since we need to capture app as well
"""
from django.http import HttpResponseRedirect
from django.conf import settings
from django.utils import translation


class LocaleAndAppURLMiddleware(object):
    """
    1. search for locale first
    2. see if there are acceptable apps
    3. save those matched parameters in the request
    4. strip them from the URL so we can do stuff
    """

    def process_request(self, request):
        # Find locale, app
        locale, app, path = self.split_locale_app_from_path(request.path)
        locale_app_path = self.locale_app_path(path, locale, app)

        if locale_app_path != request.path_info:
            if request.META.get("QUERY_STRING", ""):
                locale_app_path = "%s?%s" % (locale_app_path,
                request.META['QUERY_STRING'])
            return HttpResponseRedirect(locale_app_path)


        request.path_info = '/' + path
        if not locale:
            locale = settings.LANGUAGE_CODE
        translation.activate(locale)
        request.LANGUAGE_CODE = translation.get_language()

        request.APP = app


    def split_locale_app_from_path(self, path):
        locale = ''
        app    = ''
        second = ''

        # capture the first and second elements
        path = path.strip('/')

        (first, splitter, path) = path.partition('/')

        if path:
            (second, splitter, path) = path.partition('/')

        # if the 2nd matches an app, yay
        if second in settings.SUPPORTED_APPS:
            app = second
        else:
            path = u"/".join([second, path])
            second = None

        # if the first matches a locale, yay
        if first in settings.LANGUAGES.keys():
            locale = first
        elif not app and first in settings.SUPPORTED_APPS:
            app = first
        elif not second:
            path = u"/".join([first, path])

        return locale, app, path.strip('/')


    def locale_app_path(self, path, locale='', app=''):
        """
        Generate the localeurl-enabled path from a path without locale prefix.
        If the locale is empty settings.LANGUAGE_CODE is used.
        """

        url_parts = []
        if not locale:
            locale = settings.LANGUAGE_CODE

        url_parts.append(locale)

        if not app:
            first = path.partition('/')[0]
            if not first in settings.SUPPORTED_NONAPPS:
                url_parts.append(settings.DEFAULT_APP)
        else:
            url_parts.append(app)

        if path:
            url_parts.append(path)

        return u'/' + u'/'.join(url_parts) + u'/'
