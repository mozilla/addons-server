import functools

from django import http

from waffle import switch_is_active

from olympia.access import acl
from olympia.addons.decorators import addon_view
from olympia.addons.models import Addon
from olympia.amo import permissions


def addon_view_stats(f):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, *args, **kw):
        # Admins can see stats for every add-on regardless of its status.
        if acl.action_allowed_for(request.user, permissions.STATS_VIEW):
            qs = Addon.unfiltered.all
        else:
            qs = Addon.objects.not_disabled_by_mozilla

        return addon_view(f, qs)(request, *args, **{'addon_id': addon_id, **kw})

    return wrapper


def bigquery_api_view(f=None, json_default=list):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kw):
            if switch_is_active('disable-bigquery'):
                if kw.get('format') == 'csv':
                    response = http.HttpResponse(content_type='text/csv; charset=utf-8')
                else:
                    response = http.HttpResponse(
                        content_type='application/json', content=f'{json_default()}'
                    )
                response.status_code = 503
                return response

            return func(request, *args, **kw)

        return wrapper

    if f:
        return decorator(f)
    else:
        return decorator
