from django.core import urlresolvers
from django.utils.translation import ugettext as _

import jinja2

from jingo import register


@register.function
def url(viewname, *args, **kwargs):
    """Helper for Django's ``reverse`` in templates."""
    return urlresolvers.reverse(viewname, args=args, kwargs=kwargs)


@register.filter
def f(string, *args, **kwargs):
    """Uses ``str.format`` for string interpolation."""
    return string.format(*args, **kwargs)


@register.filter
def nl2br(string):
    return jinja2.Markup('<br>'.join(jinja2.escape(string).splitlines()))


@register.filter
def datetime(t, format=_('%B %d, %Y')):
    return t.strftime(format)
