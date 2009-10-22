from django.core import urlresolvers

from jingo import register


@register.function
def url(viewname, *args, **kwargs):
    """Helper for Django's ``reverse`` in templates."""
    return urlresolvers.reverse(viewname, args=args, kwargs=kwargs)
