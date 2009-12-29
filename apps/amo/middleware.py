"""
Borrowed from: http://code.google.com/p/django-localeurl

Note: didn't make sense to use localeurl since we need to capture app as well
"""
from django.http import HttpResponseRedirect
from django.utils import translation

from .url_prefix import Prefixer


class LocaleAndAppURLMiddleware(object):
    """
    1. search for locale first
    2. see if there are acceptable apps
    3. save those matched parameters in the request
    4. strip them from the URL so we can do stuff
    """

    def process_request(self, request):
        # Find locale, app
        prefixer = Prefixer(request)
        full_path = prefixer.fix(prefixer.shortened_path)

        if full_path != request.path_info:
            query_string = request.META.get('QUERY_STRING', '')
            if query_string:
                full_path = "%s?%s" % (full_path, query_string)
            return HttpResponseRedirect(full_path)

        request.path_info = '/' + prefixer.shortened_path
        translation.activate(prefixer.locale)
        request.APP = prefixer.app
