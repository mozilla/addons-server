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
    """
    Uses ``str.format`` for string interpolation.

    >>> {{ "{0} arguments and {x} arguments"|f('positional', x='keyword') }}
    "positional arguments and keyword arguments"
    """
    return string.format(*args, **kwargs)


@register.filter
def nl2br(string):
    return jinja2.Markup('<br>'.join(jinja2.escape(string).splitlines()))


@register.filter
def datetime(t, format=_('%B %d, %Y')):
    return t.strftime(format)


@register.filter
def selected(a, b, text='selected'):
    """Return ``text`` if ``a == b``."""
    return jinja2.Markup(text if a == b else '')


@register.filter
def class_selected(a, b):
    """Return ``'class="selected"'`` if ``a == b``."""
    return selected(a, b, 'class="selected"')
