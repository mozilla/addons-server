import hashlib
from time import time

from django.conf import settings
from django.utils import translation

from jingo import register, env
import jinja2

from .models import Session as CakeSession


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
    """
    Builds a remora-style URL, independent from Zamboni's prefixer logic.
    If app and/or lang are None, the current Zamboni values will be used.
    To omit them from the URL, set them to ''.
    """
    if lang is None:
        lang = translation.to_locale(context['LANG']).replace('_', '-')
    if app is None:
        try:
            app = context['APP'].short
        except AttributeError:
            app = None

    url_parts = [prefix, lang, app, url]
    url_parts = [p.strip('/') for p in url_parts if p]

    return '/'+'/'.join(url_parts)
