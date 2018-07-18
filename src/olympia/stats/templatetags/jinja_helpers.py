from django.template import loader

import jinja2

from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.bandwagon.models import Collection


@library.global_function
@jinja2.contextfunction
def report_menu(context, request, report, obj=None):
    """Reports Menu. navigation for the various statistic reports."""
    if obj:
        if isinstance(obj, Addon):
            has_privs = False
            if request.user.is_authenticated() and (
                acl.action_allowed(request, amo.permissions.STATS_VIEW)
                or obj.has_author(request.user)
            ):
                has_privs = True
            t = loader.get_template('stats/addon_report_menu.html')
            c = {'addon': obj, 'has_privs': has_privs}
            return jinja2.Markup(t.render(c))
        if isinstance(obj, Collection):
            t = loader.get_template('stats/collection_report_menu.html')
            c = {'collection': obj}
            return jinja2.Markup(t.render(c))

    t = loader.get_template('stats/global_report_menu.html')
    return jinja2.Markup(t.render())
