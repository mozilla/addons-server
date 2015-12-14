from django.conf import settings

from jingo import register


@register.function
def fxa_config():
    return {camel_case(key): value
            for key, value in settings.FXA_CONFIG.iteritems()
            if key != 'client_secret'}


def camel_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])
