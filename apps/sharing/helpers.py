from jingo import register, env
import jinja2

import sharing
from .models import ServiceBase, EMAIL


@register.inclusion_tag('sharing/addon_sharing.html')
@jinja2.contextfunction
def addon_sharing(context, addon):
    # prepare services
    opts = {}
    for service in sharing.SERVICES_LIST:
        service_opts = {}
        if service == EMAIL and not context['request'].user.is_authenticated():
            service_opts['url'] = '/users/login' # TODO reverse URL
            service_opts['target'] = '_self'
        else:
            service_opts['url'] = '/addon/share/{id}?service={name}'.format(
                id=addon.id, name=service.shortname)
            service_opts['target'] = '_blank'
        opts[service] = service_opts

    c = dict(context.items())
    c.update({
        'request': context['request'],
        'user': context['request'].user,
        'addon': addon,
        'services': sharing.SERVICES_LIST,
        'service_opts': opts,
        'email_service': EMAIL,
    })
    return c
