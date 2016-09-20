import os
from base64 import urlsafe_b64encode
from urllib import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url


def fxa_config(request):
    config = {camel_case(key): value
              for key, value in settings.FXA_CONFIG['default'].iteritems()
              if key != 'client_secret'}
    if request.user.is_authenticated():
        config['email'] = request.user.email
    request.session.setdefault('fxa_state', generate_fxa_state())
    config['state'] = request.session['fxa_state']
    return config


def fxa_login_url(config, state, next_path=None, action=None):
    if next_path and is_safe_url(next_path):
        state += ':' + urlsafe_b64encode(next_path.encode('utf-8')).rstrip('=')
    query = {
        'client_id': config['client_id'],
        'redirect_url': config['redirect_url'],
        'scope': config['scope'],
        'state': state,
    }
    if action is not None:
        query['action'] = action
    return '{host}/authorization?{query}'.format(
        host=config['oauth_host'], query=urlencode(query))


def default_fxa_register_url(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signup')


def default_fxa_login_url(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signin')


def generate_fxa_state():
    return os.urandom(32).encode('hex')


def redirect_for_login(request):
    return HttpResponseRedirect(default_fxa_login_url(request))


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return u'{next_path}?{qs}'.format(next_path=next_path, qs=qs)
    else:
        return next_path


def camel_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])
