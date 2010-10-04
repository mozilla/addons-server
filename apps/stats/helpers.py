from django.conf import settings

import jinja2

from jingo import register, env
from tower import ugettext as _
from amo.helpers import locale_url


@register.inclusion_tag('stats/report_menu.html')
@jinja2.contextfunction
def report_menu(context, addon, report):

    report_tree = [
        {
            'name': 'overview',
            'url': '/',
            'title': _('Overview'),
        },
        {
            'name': 'downloads',
            'url': '/downloads/',
            'title': _('Downloads'),
            'children': [
                {
                    'name': 'sources',
                    'url': '/downloads/sources/',
                    'title': _('by Download Source'),
                },
            ]
        },
        {
            'name': 'usage',
            'url': '/usage/',
            'title': _('Daily Users'),
            'children': [
                {
                    'name': 'versions',
                    'url': '/usage/versions/',
                    'title': _('by Add-on Version')
                },
                {
                    'name': 'apps',
                    'url': '/usage/applications/',
                    'title': _('by Application')
                },
                {
                    'name': 'locales',
                    'url': '/usage/languages/',
                    'title': _('by Language')
                },
                {
                    'name': 'os',
                    'url': '/usage/os/',
                    'title': _('by Operating System')
                },
                {
                    'name': 'status',
                    'url': '/usage/status/',
                    'title': _('by Add-on Status')
                },
            ]
        },
        {
            'name': 'contributions',
            'url': '/contributions/',
            'title': _('Contributions')
        },
    ]

    base_url = '/addon/%d/statistics' % (addon.id)

    """Reports Menu. navigation for the various statistic reports."""
    c = {'report': report,
        'base_url': locale_url(base_url),
        'report_tree': report_tree}
    return c
