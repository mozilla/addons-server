import jinja2

from jingo import env, register
from tower import ugettext as _
from access import acl
from addons.models import Addon
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
                addon.has_author(request.amo_user))):
                has_privs = True
            t = env.get_template('stats/addon_report_menu.html')
            c = {
                'addon': obj,
                'has_privs': has_privs
            }
            return jinja2.Markup(t.render(c))

    t = env.get_template('stats/global_report_menu.html')
    return jinja2.Markup(t.render())
