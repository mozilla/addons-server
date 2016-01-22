from jingo import register
import jinja2

from olympia import sharing


@register.inclusion_tag('sharing/sharing_widget.html')
@jinja2.contextfunction
def sharing_widget(context, obj, condensed=False):
    c = dict(context.items())
    services = sharing.get_services()

    c.update({
        'condensed': condensed,
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
