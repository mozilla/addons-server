import copy

from django.core.urlresolvers import resolve
from django.utils.cache import patch_vary_headers

from mkt.carriers import get_carrier


class HijackRedirectMiddleware(object):
    """
    This lets us hijack redirects so we directly return fragment responses
    instead of redirecting and doing lame synchronous page requests.
    """

    def process_response(self, request, response):
        if (request.method == 'POST' and
                request.POST.get('_hijacked', False) and
                response.status_code in (301, 302)):
            view_url = location = response['Location']

            # TODO: We should remove the need for this.
            if get_carrier():
                # Strip carrier from URL.
                view_url = '/' + '/'.join(location.split('/')[2:])

            r = copy.copy(request)
            r.method = 'GET'
            # We want only the fragment response.
            r.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
            # Pass back the URI so we can pushState it.
            r.FRAGMENT_URI = location
            view = resolve(view_url)
            response = view.func(r, *view.args, **view.kwargs)
        return response


class VaryOnAJAXMiddleware(object):

    def process_response(self, request, response):
        patch_vary_headers(response, ['X-Requested-With'])
        return response
