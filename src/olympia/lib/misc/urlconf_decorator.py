"""
Apply a decorator to a whole urlconf instead of a single view function.

Usage::

    >>> from urlconf_decorator import decorate
    >>>
    >>> def dec(f):
    ...     def wrapper(*args, **kw):
    ...         print 'inside the decorator'
    ...         return f(*args, **kw)
    ...     return wrapper
    >>>
    >>> urlpatterns = patterns(''
    ...     url('^admin/', decorate(dec, include(admin.site.urls))),
    ... )

The decorator applied to the urlconf is a normal function decorator.  It gets
wrapped around each callback in the urlconf as if you had @decorator above the
function.

"""
try:
    from django.urls import URLPattern, URLResolver
except ImportError:
    # django1.11
    from django.urls import (
        RegexURLPattern as URLPattern,
        RegexURLResolver as URLResolver,
    )


def decorate(decorator, urlconf):
    if isinstance(urlconf, (list, tuple)):
        for item in urlconf:
            decorate(decorator, item)
    elif isinstance(urlconf, URLResolver):
        for item in urlconf.url_patterns:
            decorate(decorator, item)
    elif isinstance(urlconf, URLPattern):
        urlconf._callback = decorator(urlconf.callback)
    return urlconf
