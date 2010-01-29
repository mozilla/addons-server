from django.conf import settings
from django.core.urlresolvers import reverse as django_reverse
from django.utils.thread_support import currentThread

import amo.models


# Thread-local storage for URL prefixes.  Access with {get,set}_url_prefix.
_prefixes = {}


def set_url_prefix(prefix):
    """Set ``prefix`` for the current thread."""
    _prefixes[currentThread()] = prefix


def get_url_prefix():
    """Get the prefix for the current thread, or None."""
    return _prefixes.get(currentThread())


def reverse(viewname, urlconf=None, args=None, kwargs=None, prefix=None,
            current_app=None):
    """Wraps django's reverse to prepend the correct locale and app."""
    prefixer = get_url_prefix()
    url = django_reverse(viewname, urlconf, args, kwargs, prefix, current_app)
    if prefixer:
        return prefixer.fix(url)
    else:
        return url


class Prefixer(object):

    def __init__(self, request):
        self.request_path = request.path

        self.locale, self.app, self.shortened_path = self.split_request()

    def split_request(self):
        """
        Split the requested path into (locale, app, remainder).

        locale and app will be empty strings if they're not found.
        """
        path = self.request_path.lstrip('/')

        # Use partition instead of split since it always returns 3 parts.
        first, _, first_rest = path.partition('/')
        second, _, rest = first_rest.partition('/')

        if first in settings.LANGUAGES:
            if second in amo.APPS:
                return first, second, rest
            else:
                return first, '', first_rest
        elif first in amo.APPS:
            return '', first, first_rest
        else:
            if second in amo.APPS:
                return '', second, rest
            else:
                return '', '', path

    def fix(self, path):
        path = path.lstrip('/')
        url_parts = []

        locale = self.locale if self.locale else settings.LANGUAGE_CODE
        url_parts.append(locale)

        if path.partition('/')[0] not in settings.SUPPORTED_NONAPPS:
            app = self.app if self.app else settings.DEFAULT_APP
            url_parts.append(app)

        url_parts.append(path)

        return '/' + '/'.join(url_parts)
