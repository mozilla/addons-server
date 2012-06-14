from django.utils.http import urlquote

from jingo import register
import jinja2

from access import acl


@register.function
@jinja2.contextfunction
def check_contrib_stats_perms(context, addon):
    request = context['request']
    if addon.has_author(request.amo_user) or acl.action_allowed(request,
        'RevenueStats', 'View'):
        return True


@register.function
def url_quote(url):
    return urlquote(url)
