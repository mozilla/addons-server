import functools
import types

import utils


URL_SEGMENT_TYPES = types.StringTypes + (int, long, )

def bust_fragments_on_post(url_prefix, bust_on_2xx=True, bust_on_3xx=True):
    """
    Set a cookie to bust the fragment cache for a specific URL prefix. Must be
    applied before any decorators that modify args/kwargs is applied.

    `url_prefix`
        The URL prefix to set the cache-busting flag for. This can be a string
        or a list of strings.
    `bust_on_2xx`
        If True (default), the cookie will be set when the page response is a
        200.
    `bust_on_3xx`
        If True (default), the cookie will be set when the page response is a
        300.
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapper(request, *args, **kwargs):
            # Make sure that nobody gets silly and uses a magic decorator
            # before they use this decorator.
            passed_values = args + tuple(kwargs.values())
            assert all(
                isinstance(a, URL_SEGMENT_TYPES) for a in passed_values), (
                "You're doing this in the wrong order. `bust_fragments_*` "
                'goes on the outside. Called with: %s' %
                ', '.join(map(str, map(type, passed_values))))

            response = f(request, *args, **kwargs)

            # This function only busts POST requests.
            if request.method != 'POST':
                return response

            status_code = response.status_code
            status_code -= status_code % 100
            # Ignore status codes that we don't plan on busting for.
            if (status_code not in (200, 300, ) or
                status_code == 200 and not bust_on_2xx or
                status_code == 300 and not bust_on_3xx):
                return response

            utils.bust_fragments(response, url_prefix, *args, **kwargs)
            return response

        return wrapper
    return decorator
