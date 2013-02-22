import copy
import json
import urllib

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
            frag_bust = response.get('x-frag-bust', None)

            # TODO: We should remove the need for this.
            if get_carrier():
                # Strip carrier from URL.
                view_url = '/' + '/'.join(location.split('/')[2:])

            req = copy.copy(request)
            req.method = 'GET'
            req.path = view_url
            # We want only the fragment response.
            req.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
            # Pass back the URI so we can pushState it.
            req.FRAGMENT_URI = location

            view = resolve(urllib.unquote(view_url).decode('utf-8'))
            response = view.func(req, *view.args, **view.kwargs)

            response['X-URI'] = location
            # If we have a fragment cache bust flag on the first request,
            # perpetrate it on the new request.
            if frag_bust:
                # If there's a fragment bust flag in the new request, merge it
                # with the flag from the old request in the second grossest
                # possible way.
                if 'x-frag-bust' in response:
                    frag_bust = json.dumps(
                        json.loads(frag_bust) +
                        json.loads(response['x-frag-bust']))

                response['x-frag-bust'] = frag_bust

        return response


class VaryOnAJAXMiddleware(object):

    def process_response(self, request, response):
        patch_vary_headers(response, ['X-Requested-With'])
        return response
