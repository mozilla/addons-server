import jinja2
import waffle

from jingo import env, register
from tower import ugettext as _
from access import acl
from addons.models import Addon
from bandwagon.models import Collection
from amo.urlresolvers import reverse


@register.function
@jinja2.contextfunction
def report_menu(context, request, report, obj=None):
    """Reports Menu. navigation for the various statistic reports."""
    if obj:
        if isinstance(obj, Addon):
            has_privs = False
            if (request.user.is_authenticated() and (
                acl.action_allowed(request, 'Stats', 'View') or
                obj.has_author(request.amo_user))):
                has_privs = True
            t = env.get_template('stats/addon_report_menu.html')
            if obj.is_webapp() and waffle.switch_is_active('marketplace'):
                t = env.get_template('appstats/app_report_menu.html')
            c = {
                'addon': obj,
                'has_privs': has_privs
            }
            return jinja2.Markup(t.render(c))
        if isinstance(obj, Collection):
            t = env.get_template('stats/collection_report_menu.html')
            c = {
                'collection': obj,
            }
            return jinja2.Markup(t.render(c))

    t = env.get_template('stats/global_report_menu.html')
    return jinja2.Markup(t.render())
