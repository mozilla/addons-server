from operator import attrgetter

import caching.base as caching
import jinja2
from jingo import register, env

import amo
from addons.models import Category


@register.function
@jinja2.contextfunction
def apps_site_nav(context):
    return caching.cached(lambda: _apps_site_nav(context), 'site-nav-apps')


def _apps_site_nav(context):
    qs = Category.objects.filter(weight__gte=0, type=amo.ADDON_WEBAPP)
    cats = sorted(qs, key=attrgetter('weight', 'name'))
    ctx = dict(request=context['request'], amo=amo, cats=cats)
    return jinja2.Markup(env.get_template('webapps/site_nav.html').render(ctx))
