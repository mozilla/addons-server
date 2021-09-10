from django.template import loader

import jinja2
import markupsafe

from django_jinja import library

from olympia.addons.models import Addon


@library.global_function
@jinja2.pass_context
def report_menu(context, request, report, obj):
    """Renders navigation for the various statistic reports."""
    if isinstance(obj, Addon):
        tpl = loader.get_template('stats/addon_report_menu.html')
        ctx = {
            'has_listed_versions': obj.has_listed_versions(include_deleted=True),
            'slug_or_id': obj.id if obj.is_deleted else obj.slug,
        }
        return markupsafe.Markup(tpl.render(ctx))
