from django.conf import settings

import jingo


def render_error(request, exc, exc_class=None):
    if not exc_class:
        exc_class = exc.__class__.__name__
    ctx = {}
    if settings.INAPP_VERBOSE_ERRORS:
        ctx['exc_class'] = exc_class
        ctx['exc_message'] = exc
    return jingo.render(request, 'inapp_pay/error.html', ctx)
