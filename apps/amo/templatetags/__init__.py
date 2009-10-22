import jinja2

from jingo import register, env


@register.filter
def paginator(pager):
    c = {'pager': pager, 'num_pages': pager.paginator.num_pages,
         'count': pager.paginator.count}
    t = env.get_template('amo/paginator.html').render(**c)
    return jinja2.Markup(t)
