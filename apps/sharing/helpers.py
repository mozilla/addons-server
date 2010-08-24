from jingo import register, env
import jinja2

import sharing
from amo.helpers import login_link
from .models import ServiceBase, EMAIL


@register.inclusion_tag('sharing/sharing_box.html')
@jinja2.contextfunction
def sharing_box(context, obj, show_email=True):
    request = context['request']
    opts = {}
    services = list(sharing.SERVICES_LIST)
    if not show_email:
        services.remove(EMAIL)
    for service in sharing.SERVICES_LIST:
        service_opts = {}
        if service == EMAIL and not request.user.is_authenticated():
            service_opts['url'] = login_link(context)
            service_opts['target'] = '_self'
        else:
            url = obj.share_url() + '?service=%s' % service.shortname
            service_opts['url'] = url
            service_opts['target'] = '_blank'
        opts[service] = service_opts

    c = dict(context.items())
    c.update({
        'request': request,
        'user': request.user,
        'obj': obj,
        'services': services,
        'service_opts': opts,
        'email_service': EMAIL,
        'show_email': show_email,
    })
    return c
