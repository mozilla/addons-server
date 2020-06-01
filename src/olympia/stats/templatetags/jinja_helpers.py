from django.template import loader

import jinja2

from django.urls import reverse
from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon


@library.global_function
@jinja2.contextfunction
def report_menu(context, request, report, obj):
    """Renders navigation for the various statistic reports."""
    if isinstance(obj, Addon):
        has_privs = False
        if request.user.is_authenticated and (
            acl.action_allowed(request, amo.permissions.STATS_VIEW) or
            obj.has_author(request.user)
        ):
            has_privs = True
        tpl = loader.get_template('stats/addon_report_menu.html')
        ctx = {
            'addon': obj,
            'has_privs': has_privs,
            'beta': context.get('beta', False),
        }
        return jinja2.Markup(tpl.render(ctx))


@library.global_function
@jinja2.contextfunction
def stats_url(context, name, *args):
    url_name = f'{name}.beta' if context.get('beta', False) else name
    return reverse(url_name, args=args)
