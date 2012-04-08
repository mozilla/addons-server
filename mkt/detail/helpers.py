from addons.models import DeviceType
from jingo import env, register
import jinja2


@register.function
def device_list(product):
    device_types = product.device_types
    all_device_types = DeviceType.objects.all()
    if device_types:
        t = env.get_template('detail/helpers/device_list.html')
        return jinja2.Markup(t.render(device_types=device_types,
        							  all_device_types=all_device_types))
