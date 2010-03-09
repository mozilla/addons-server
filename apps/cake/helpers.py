import hashlib
from time import time

from django.conf import settings

import jinja2

from jingo import register, env

from .models import Session as CakeSession


@register.function
@jinja2.contextfunction
def cake_csrf_token(context):
    """Generate a CSRF token that Remora can read."""
    user = context['request'].user
    if not user.is_authenticated():
        return

    try:
        session_id = context['request'].COOKIES.get('AMOv3').value
        assert session_id
    except (AttributeError, AssertionError):
        return

    try:
        session = CakeSession.objects.get(pk=session_id)
        epoch = int(time() / settings.CAKE_SESSION_TIMEOUT)
        token = '%s%s%s' % (session.pk, user.id, epoch)
        return jinja2.Markup(
            '<div class="hsession"><input type="hidden" name="sessionCheck" '
            'value="%s"/></div>' % hashlib.md5(token).hexdigest())

    except CakeSession.DoesNotExist:
        return
