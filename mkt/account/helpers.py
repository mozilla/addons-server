from jingo import register
import jinja2

from mkt.site.helpers import new_context


@register.inclusion_tag('account/helpers/refund_info.html')
@jinja2.contextfunction
def refund_info(context, product, contributions, show_link):
    return new_context(**locals())
