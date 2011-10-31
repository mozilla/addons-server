from jingo import register
import jinja2

import sharing
from django.utils import encoding


@register.inclusion_tag('sharing/sharing_widget.html')
@jinja2.contextfunction
def sharing_widget(context, obj, condensed=False):
    c = dict(context.items())

    services = sharing.get_services()

    counts = {}
    for service in services:
        short = encoding.smart_str(service.shortname)
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

    services = sharing.get_services()

    c = dict(context.items())
    c.update({
        'request': request,
        'user': request.user,
        'services': services
    })
    return c
