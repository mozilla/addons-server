from jingo import register, env
import jinja2

import sharing
from amo.helpers import login_link


@register.inclusion_tag('sharing/sharing_widget.html')
@jinja2.contextfunction
def sharing_widget(context, obj, condensed=False):
    c = dict(context.items())

    services = list(sharing.SERVICES_LIST)

    counts = {}
    for service in services:
        short = service.shortname
        counts[short] = service.count_term(obj.share_counts[short])

    c.update({
        'condensed': condensed,
        'base_url': obj.share_url(),
        'counts': counts,
        'services': services,
        'obj': obj,
    })
    return c


@register.inclusion_tag('sharing/sharing_box.html')
@jinja2.contextfunction
def sharing_box(context):
    request = context['request']

    c = dict(context.items())
    c.update({
        'request': request,
        'user': request.user,
        'services': sharing.SERVICES_LIST,
    })
    return c
