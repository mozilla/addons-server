from threading import local

from django import urls


# Get a pointer to Django's reverse and resolve because we're going to hijack
# them after we define our own.
# As we're using a url prefixer to automatically add the locale and the app to
# URLs, we're not compatible with Django's default reverse and resolve, and
# thus need to monkeypatch them.
django_reverse = urls.reverse
django_resolve = urls.resolve


# Thread-local storage for URL prefixes.  Access with {get,set}_url_prefix.
_local = local()


def set_url_prefix(prefix):
    """Set ``prefix`` for the current thread."""
    _local.prefix = prefix


def get_url_prefix():
    """Get the prefix for the current thread, or None."""
    return getattr(_local, 'prefix', None)


def clean_url_prefixes():
    """Purge prefix cache."""
    if hasattr(_local, 'prefix'):
        delattr(_local, 'prefix')


def reverse(
    viewname, urlconf=None, args=None, kwargs=None, current_app=None, add_prefix=True
):
    """Wraps django's reverse to prepend the correct locale and app."""
    prefixer = get_url_prefix()
    url = django_reverse(viewname, urlconf, args, kwargs, current_app)
    if prefixer and add_prefix:
        return prefixer.fix(url)
    else:
        return url


# Replace Django's reverse with our own.
urls.reverse = reverse


def resolve(path, urlconf=None):
    """Wraps django's resolve to remove the locale and app from the path."""
    prefixer = get_url_prefix()
    if prefixer:
        _lang, application, path_fragment = prefixer.split_path(path)
        path = '/%s' % path_fragment
    return django_resolve(path, urlconf)


# Replace Django's resolve with our own.
urls.resolve = resolve
