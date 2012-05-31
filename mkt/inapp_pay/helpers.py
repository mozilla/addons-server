from django.conf import settings

import jingo

from .models import InappConfig


def render_error(request, exc, exc_class=None):
    if not exc_class:
        exc_class = exc.__class__.__name__
    ctx = {}
    if settings.INAPP_VERBOSE_ERRORS:
        ctx['exc_class'] = exc_class
        ctx['exc_message'] = exc
    app_id = exc.app_id if hasattr(exc, 'app_id') else None
    qs = (InappConfig.objects.filter(public_key=app_id)
                             .select_related('addon'))
    if qs.exists():
        ctx['config'] = qs.get()
    else:
        ctx['config'] = None
    return jingo.render(request, 'inapp_pay/error.html', ctx)
