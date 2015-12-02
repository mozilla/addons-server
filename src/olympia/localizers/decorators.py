from functools import wraps

from django import http
from django.conf import settings
from django.http import Http404

from amo.urlresolvers import reverse


def locale_switcher(f):
    """Decorator redirecting clicks on the locale switcher dropdown."""
    @wraps(f)
    def decorated(request, *args, **kwargs):
        new_userlang = request.GET.get('userlang')
        if new_userlang in settings.AMO_LANGUAGES + settings.HIDDEN_LANGUAGES:
            kwargs['locale_code'] = new_userlang
            to = reverse(decorated, args=args, kwargs=kwargs)
            return http.HttpResponseRedirect(to)
        else:
            return f(request, *args, **kwargs)
    return decorated


def valid_locale(f):
    """Decorator validating locale code for per-language pages."""
    @wraps(f)
    def decorated(request, locale_code, *args, **kwargs):
        if locale_code not in (settings.AMO_LANGUAGES +
                               settings.HIDDEN_LANGUAGES):
            raise Http404
        return f(request, locale_code, *args, **kwargs)
    return decorated
