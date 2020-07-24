from django.template import loader

import jinja2
import waffle

from django_jinja import library

from olympia.addons.models import Addon


@library.global_function
@jinja2.contextfunction
def report_menu(context, request, report, obj):
    """Renders navigation for the various statistic reports."""
    if isinstance(obj, Addon):
        tpl = loader.get_template('stats/addon_report_menu.html')
        ctx = {
            'addon': obj,
            'bigquery_download_stats': waffle.flag_is_active(
                request, 'bigquery-download-stats'
            ),
        }
        return jinja2.Markup(tpl.render(ctx))
