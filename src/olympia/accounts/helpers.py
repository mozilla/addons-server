import jinja2
from jingo import register

from olympia.accounts import utils


@register.function
@jinja2.contextfunction
def login_link(context):
    return utils.default_fxa_login_url(context['request'])


@register.function
@jinja2.contextfunction
def register_link(context):
    return utils.default_fxa_register_url(context['request'])


@register.function
@jinja2.contextfunction
def fxa_config(context):
    return utils.fxa_config(context['request'])
