from jingo import register, env
import jinja2

import sharing
from .models import ServiceBase, EMAIL


@register.function
@jinja2.contextfunction
def addon_sharing(context, addon):
    t = env.get_template('sharing/addon_sharing.html')

    # prepare services
    opts = {}
    for service in sharing.SERVICES_LIST:
        service_opts = {}
        if service == EMAIL:
            if context['request'].user.is_authenticated():
                service_opts['url'] = '#'
            else:
                service_opts['url'] = '/users/login' # TODO reverse URL
            service_opts['target'] = ''
        else:
            service_opts['url'] = '/addon/share/{id}?service={name}'.format(
                id=addon.id, name=service.shortname)
            service_opts['target'] = '_blank'
        opts[service] = service_opts

    # all shares for this add-on: not evaluated, but cached against
    all_shares = ServiceBase.all_shares(addon)

    data = {
        'request': context['request'],
        'user': context['request'].user,
        'addon': addon,
        'services': sharing.SERVICES_LIST,
        'service_opts': opts,
        'email_service': EMAIL,
        'all_shares': all_shares
    }
    return jinja2.Markup(t.render(**data))
