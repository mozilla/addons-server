import hashlib
from time import time

from django.conf import settings
from django.utils import translation

from jingo import register, env
import jinja2

from .models import Session as CakeSession
from .urlresolvers import remora_url as remora_urlresolver


@register.function
@jinja2.contextfunction
def cake_csrf_token(context):
    """Generate a CSRF token that Remora can read."""
    user = context['request'].user
    if not user.is_authenticated():
        return

    try:
        session_id = context['request'].COOKIES['AMOv3']
        assert session_id
    except (KeyError, AssertionError):
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


@register.function
@jinja2.contextfunction
def remora_url(context, url, lang=None, app=None, prefix=''):
    """Wrapper for urlresolvers.remora_url"""
    if lang is None:
        _lang = context['LANG']
        if _lang:
            lang = translation.to_locale(_lang).replace('_', '-')
    if app is None:
        try:
            app = context['APP'].short
        except AttributeError, KeyError:
            pass
    return remora_urlresolver(url=url, lang=lang, app=app, prefix=prefix)
