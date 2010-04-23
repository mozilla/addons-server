"""
Borrowed from: http://code.google.com/p/django-localeurl

Note: didn't make sense to use localeurl since we need to capture app as well
"""
import urllib
from datetime import datetime, timedelta

from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponsePermanentRedirect
from django.utils.encoding import smart_str
from django.utils import translation

import tower

import amo
from . import urlresolvers
from .helpers import urlparams
from zadmin.models import Config

NEXT_YEAR = datetime.strftime(datetime.utcnow() +
        timedelta(seconds=365 * 24 * 60 * 60), "%a, %d-%b-%Y %H:%M:%S GMT")


class LocaleAndAppURLMiddleware(object):
    """
    1. Search for locale first.
    2. See if there are acceptable apps.
    3. Save those matched parameters in the request.
    4. Strip them from the URL so we can do stuff.
    5. Process locale-only (xenophobia) since it's submitted with 'lang'.
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
            query = dict((smart_str(k), v) for k, v in request.GET.items()
                         if k not in ('lang', 'locale-only'))

            response = HttpResponsePermanentRedirect(
                    urlparams(new_path, **query))

            xenophobia = 0

            # User checked a box is the only reason this would happen.
            if 'locale-only' in request.GET:
                xenophobia = 1

            response.set_cookie('locale-only', xenophobia, expires=NEXT_YEAR)
            return response

        if full_path != request.path:
            query_string = request.META.get('QUERY_STRING', '')
            full_path = urllib.quote(full_path.encode('utf-8'))

            if query_string:
                full_path = "%s?%s" % (full_path, query_string)

            response = HttpResponsePermanentRedirect(full_path)

            # Vary on Accept-Language if we changed the locale.
            old_locale = prefixer.locale
            new_locale, _, _ = prefixer.split_path(full_path)
            if old_locale != new_locale:
                response['Vary'] = 'Accept-Language'
            return response

        request.path_info = '/' + prefixer.shortened_path
        tower.activate(prefixer.locale)
        request.APP = amo.APPS.get(prefixer.app)

        if 'locale-only' in request.COOKIES:
            request.XENOPHOBIA = (request.COOKIES['locale-only'] == '1')
        else:
            try:
                conf = Config.objects.get(pk='xenophobia')
                request.XENOPHOBIA = conf.json.get(
                        translation.get_language(), False)
            except Config.DoesNotExist:
                request.XENOPHOBIA = False


class NoVarySessionMiddleware(SessionMiddleware):
    """
    SessionMiddleware sets Vary: Cookie anytime request.session is accessed.
    request.session is accessed indirectly anytime request.user is touched.
    We always touch request.user to see if the user is authenticated, so every
    request would be sending vary, so we'd get no caching.

    We skip the cache in Zeus if someone has an AMOv3 cookie, so varying on
    Cookie at this level only hurts us.
    """

    def process_response(self, request, response):
        # Let SessionMiddleware do its processing but prevent it from changing
        # the Vary header.
        vary = response.get('Vary', None)
        new_response = (super(NoVarySessionMiddleware, self)
                        .process_response(request, response))
        if vary:
            new_response['Vary'] = vary
        else:
            del new_response['Vary']
        return new_response
