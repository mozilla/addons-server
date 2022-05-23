import os

from django import http
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control, patch_vary_headers

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon, AddonRegionalRestrictions
from olympia.amo.decorators import api_authentication
from olympia.amo.utils import HttpResponseXSendFile
from olympia.files.models import File
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.versions')


@addon_view_factory(lambda: Addon.objects.public().no_transforms())
@non_atomic_requests
def update_info(request, addon, version_num):
    version = get_object_or_404(
        addon.versions.reviewed()
        .filter(channel=amo.RELEASE_CHANNEL_LISTED)
        .only_translations(),
        version=version_num,
    )
    response = TemplateResponse(
        request,
        'versions/update_info.html',
        context={'version': version},
        content_type='application/xhtml+xml',
    )
    patch_cache_control(response, max_age=60 * 60)
    return response


@non_atomic_requests
def update_info_redirect(request, version_id):
    version = get_object_or_404(
        Version.objects.reviewed()
        .filter(channel=amo.RELEASE_CHANNEL_LISTED)
        .no_transforms()
        .select_related('addon'),
        pk=version_id,
    )
    if not version.addon.is_public():
        raise http.Http404()
    response = redirect(
        reverse(
            'addons.versions.update_info', args=(version.addon.slug, version.version)
        ),
        permanent=True,
    )
    patch_cache_control(response, max_age=60 * 60)
    return response


@non_atomic_requests
@api_authentication
def download_file(request, file_id, download_type=None, **kwargs):
    """
    Download the file identified by `file_id` parameter.

    If the file is disabled or belongs to an unlisted version, requires an
    add-on developer or appropriate reviewer for the channel. If the file is
    deleted or belongs to a deleted version or add-on, reviewers can still
    access but developers can't.
    """

    def is_appropriate_reviewer(addon, channel):
        return (
            acl.is_reviewer(request.user, addon)
            if channel == amo.RELEASE_CHANNEL_LISTED
            else acl.is_unlisted_addons_viewer_or_reviewer(request.user)
        )

    file_ = get_object_or_404(File.objects, pk=file_id)
    # Include deleted add-ons in the queryset, we'll check for that below.
    addon = get_object_or_404(
        Addon.unfiltered.all().no_transforms(), pk=file_.version.addon_id
    )
    version = file_.version
    channel = version.channel

    if version.deleted or addon.is_deleted:
        # Only the appropriate reviewer can see deleted things.
        has_permission = is_appropriate_reviewer(addon, channel)
        apply_georestrictions = False
    elif (
        addon.is_disabled
        or file_.status == amo.STATUS_DISABLED
        or channel == amo.RELEASE_CHANNEL_UNLISTED
    ):
        # Only the appropriate reviewer or developers of the add-on can see
        # disabled or unlisted things.
        has_permission = is_appropriate_reviewer(
            addon, channel
        ) or acl.check_addon_ownership(
            request.user,
            addon,
            allow_developer=True,
            allow_mozilla_disabled_addon=True,
            allow_site_permission=True,
        )
        apply_georestrictions = False
    else:
        # Public case: we're either directly downloading the file or
        # redirecting, but in any case we have permission in the general sense,
        # though georestrictions are in effect.
        has_permission = True
        apply_georestrictions = True

    region_code = request.META.get('HTTP_X_COUNTRY_CODE', None)
    # Whether to set Content-Disposition: attachment header or not, to force
    # the file to be downloaded rather than installed (used by admin/reviewer
    # tools).
    attachment = download_type == 'attachment'
    if not has_permission:
        log.debug(
            'download file {file_id}: addon/version/file not public and '
            'user {user_id} does not have relevant permissions.'.format(
                file_id=file_id, user_id=request.user.pk
            )
        )
        response = http.HttpResponseNotFound()
    elif (
        apply_georestrictions
        and region_code
        and AddonRegionalRestrictions.objects.filter(
            addon=addon, excluded_regions__contains=region_code.upper()
        ).exists()
    ):
        response = http.HttpResponse(status=451)
        url = 'https://www.mozilla.org/about/policy/transparency/'
        response['Link'] = f'<{url}>; rel="blocked-by"'
    else:
        # We're returning a X-Accel-Redirect, we can set
        # Content-Disposition: attachment ourselves in HttpResponseXSendFile:
        # nginx won't override it if present.
        response = HttpResponseXSendFile(
            request,
            file_.file_path,
            content_type='application/x-xpinstall',
            attachment=attachment,
        )
    # Always add a few headers to the response (even errors).
    patch_cache_control(response, max_age=60 * 60 * 24)
    patch_vary_headers(response, ['X-Country-Code'])
    response['Access-Control-Allow-Origin'] = '*'
    return response


@addon_view_factory(Addon.objects.public)
@non_atomic_requests
def download_latest(request, addon, download_type=None, **kwargs):
    """
    Redirect to the URL to download the file from 'current'
    (latest public listed) version of an add-on.

    Returns a 404 for add-ons that are deleted/disabled/non-public/without an
    approved listed version.
    """
    file_ = addon.current_version.file
    attachment = download_type == 'attachment'
    response = http.HttpResponseRedirect(file_.get_absolute_url(attachment=attachment))
    patch_cache_control(response, max_age=60 * 60 * 1)
    response['Access-Control-Allow-Origin'] = '*'
    return response


@non_atomic_requests
def download_source(request, version_id):
    """
    Download source code for a given version_id.

    Requires developer of the add-on or admin reviewer permission. If the
    version or add-on is deleted, developers can't access.

    If the version source code wasn't provided, but the user had the right
    permissions, a 404 is raised.
    """
    # Include deleted versions in the queryset, we'll check for that below.
    version = get_object_or_404(Version.unfiltered, pk=version_id)
    addon = version.addon

    # Channel doesn't matter, source code is only available to admin reviewers
    # or developers of the add-on. If the add-on, version or file is deleted or
    # disabled, then only admins can access.
    has_permission = acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN)

    if (
        addon.status != amo.STATUS_DISABLED
        and not version.file.status == amo.STATUS_DISABLED
        and not version.deleted
        and not addon.is_deleted
    ):
        has_permission = has_permission or acl.check_addon_ownership(
            request.user,
            addon,
            allow_addons_edit_permission=False,
            allow_developer=True,
        )
    if not has_permission:
        raise http.Http404()

    response = HttpResponseXSendFile(request, version.source.path)
    path = version.source.path
    if not isinstance(path, str):
        path = path.decode('utf8')
    name = os.path.basename(path.replace('"', ''))
    disposition = f'attachment; filename="{name}"'.encode()
    response['Content-Disposition'] = disposition
    response['Access-Control-Allow-Origin'] = '*'
    return response
