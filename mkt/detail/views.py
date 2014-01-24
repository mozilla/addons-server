import hashlib

from django import http
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import etag

import commonware.log

import amo
from addons.decorators import addon_view_factory
from amo.decorators import login_required, permission_required
from amo.utils import paginate
from devhub.models import ActivityLog

from mkt.webapps.models import Webapp

log = commonware.log.getLogger('z.detail')

addon_view = addon_view_factory(qs=Webapp.objects.valid)
addon_all_view = addon_view_factory(qs=Webapp.objects.all)


def manifest(request, uuid):
    """Returns the "mini" manifest for packaged apps.

    If not a packaged app, returns a 404.

    """
    addon = get_object_or_404(Webapp, guid=uuid, is_packaged=True)
    is_avail = addon.status in [amo.STATUS_PUBLIC, amo.STATUS_BLOCKED]
    package_etag = hashlib.sha256()

    if not addon.is_packaged or addon.disabled_by_user or not is_avail:
        raise http.Http404

    else:
        manifest_content = addon.get_cached_manifest()
        package_etag.update(manifest_content)

        if addon.is_packaged:
            # Update the hash with the content of the package itself.
            package_file = addon.get_latest_file()
            if package_file:
                package_etag.update(package_file.hash)

    manifest_etag = package_etag.hexdigest()

    @etag(lambda r, a: manifest_etag)
    def _inner_view(request, addon):
        response = http.HttpResponse(
            manifest_content,
            content_type='application/x-web-app-manifest+json; charset=utf-8')
        return response

    return _inner_view(request, addon)


@login_required
@permission_required('AccountLookup', 'View')
@addon_all_view
def app_activity(request, addon):
    """Shows the app activity age for single app."""

    user_items = ActivityLog.objects.for_apps([addon]).exclude(
        action__in=amo.LOG_HIDE_DEVELOPER)
    admin_items = ActivityLog.objects.for_apps([addon]).filter(
        action__in=amo.LOG_HIDE_DEVELOPER)

    user_items = paginate(request, user_items, per_page=20)
    admin_items = paginate(request, admin_items, per_page=20)

    return render(request, 'detail/app_activity.html',
                  {'admin_items': admin_items, 'product': addon,
                   'user_items': user_items})
