from jingo import env, register
import jinja2

from tower import ungettext as ngettext

from amo.helpers import numberfmt
from constants.applications import DEVICE_TYPES


@register.function
def device_list(product):
    device_types = product.device_types
    if device_types:
        t = env.get_template('detail/helpers/device_list.html')
        return jinja2.Markup(t.render(device_types=device_types,
                                      all_device_types=DEVICE_TYPES.values()))


@register.filter
def weekly_downloads(product):
    cnt = product.weekly_downloads
    return ngettext('{0} weekly download', '{0} weekly downloads',
                    cnt).format(numberfmt(cnt))
