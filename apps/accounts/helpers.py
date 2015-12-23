import os

from django.conf import settings

import jinja2
from jingo import register


@register.function
@jinja2.contextfunction
def fxa_config(context):
    request = context['request']
    config = {camel_case(key): value
              for key, value in settings.FXA_CONFIG.iteritems()
              if key != 'client_secret'}
    request.session.setdefault('fxa_state', generate_fxa_state())
    config['state'] = request.session['fxa_state']
    return config


def generate_fxa_state():
    return os.urandom(32).encode('hex')


def camel_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])
