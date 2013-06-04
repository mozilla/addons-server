from django.core.urlresolvers import reverse
from django.utils.functional import lazy

from rest_framework import reverse as rest_reverse


def _reverse(viewname, args=None, kwargs=None, request=None, format=None,
             **extra):
    """
    Same as the rest framework reverse, except does not get the base URL.
    """
    if format is not None:
        kwargs = kwargs or {}
        kwargs['format'] = format
    return reverse(viewname, args=args, kwargs=kwargs, **extra)

_reverse.patched = 'patched'

# Monkeypatch this in.
def patch():
    rest_reverse.reverse = _reverse
    rest_reverse.reverse_lazy = lazy(_reverse, str)
