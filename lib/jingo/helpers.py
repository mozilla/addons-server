from django.utils.translation import ugettext as _
from django.template.defaulttags import CsrfTokenNode

import jinja2

from jingo import register


@register.function
@jinja2.contextfunction
def csrf(context):
    return jinja2.Markup(CsrfTokenNode().render(context))


@register.filter
def f(string, *args, **kwargs):
    """
    Uses ``str.format`` for string interpolation.

    >>> {{ "{0} arguments and {x} arguments"|f('positional', x='keyword') }}
    "positional arguments and keyword arguments"
    """
    string = unicode(string)
    return string.format(*args, **kwargs)


@register.filter
def nl2br(string):
    return jinja2.Markup('<br>'.join(jinja2.escape(string).splitlines()))


@register.filter
def datetime(t, format=_('%B %d, %Y')):
    return t.strftime(format)


@register.filter
def ifeq(a, b, text):
    """Return ``text`` if ``a == b``."""
    return jinja2.Markup(text if a == b else '')


@register.filter
def class_selected(a, b):
    """Return ``'class="selected"'`` if ``a == b``."""
    return ifeq(a, b, 'class="selected"')
