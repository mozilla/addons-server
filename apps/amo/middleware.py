"""
Borrowed from: http://code.google.com/p/django-localeurl

Note: didn't make sense to use localeurl since we need to capture app as well
"""
import urllib

from django.http import HttpResponsePermanentRedirect
from django.utils.encoding import smart_str

import l10n

import amo.models
from . import urlresolvers
from .helpers import urlparams


class LocaleAndAppURLMiddleware(object):
    """
    1. search for locale first
    2. see if there are acceptable apps
    3. save those matched parameters in the request
    4. strip them from the URL so we can do stuff
    """

    def process_request(self, request):
        # Find locale, app
        prefixer = urlresolvers.Prefixer(request)
        urlresolvers.set_url_prefix(prefixer)
        full_path = prefixer.fix(prefixer.shortened_path)

        if 'lang' in request.GET:
            # Blank out the locale so that we can set a new one.  Remove lang
            # from query params so we don't have an infinite loop.
            prefixer.locale = ''
            new_path = prefixer.fix(prefixer.shortened_path)
            query = dict((smart_str(k), request.GET[k]) for k in request.GET)
            query.pop('lang')
            return HttpResponsePermanentRedirect(urlparams(new_path, **query))

        if full_path != request.path:
            query_string = request.META.get('QUERY_STRING', '')
            if query_string:
                full_path = "%s?%s" % (full_path, query_string)

            full_path = urllib.quote(full_path.encode('utf-8'))
            response = HttpResponsePermanentRedirect(full_path)

            # Vary on Accept-Language if we changed the locale.
            old_locale = prefixer.locale
            new_locale, _, _ = prefixer.split_path(full_path)
            if old_locale != new_locale:
                response['Vary'] = 'Accept-Language'

            return response

        request.path_info = '/' + prefixer.shortened_path
        l10n.activate(prefixer.locale)
        request.APP = amo.APPS.get(prefixer.app)
