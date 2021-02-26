import os

from django import http
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.cache import patch_vary_headers

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon, AddonRegionalRestrictions
from olympia.amo.utils import HttpResponseXSendFile, render, urlparams
from olympia.files.models import File
from olympia.versions.models import Version


# The version detail page redirects to the version within pagination, so we
# need to enforce the number of versions per page.
PER_PAGE = 30
addon_view = addon_view_factory(Addon.objects.valid)

log = olympia.core.logger.getLogger('z.versions')


@addon_view
@non_atomic_requests
def update_info(request, addon, version_num):
    version = Version.objects.filter(
        addon=addon,
        version=version_num,
        files__status__in=amo.VALID_FILE_STATUSES,
        channel=amo.RELEASE_CHANNEL_LISTED,
    ).last()
    if not version:
        raise http.Http404()
    return render(
        request,
        'versions/update_info.html',
        {'version': version},
        content_type='application/xhtml+xml',
    )


@non_atomic_requests
def update_info_redirect(request, version_id):
    version = get_object_or_404(Version.objects, pk=version_id)
    return redirect(
        reverse(
            'addons.versions.update_info', args=(version.addon.id, version.version)
        ),
        permanent=True,
    )


# Should accept junk at the end for filename goodness.
@non_atomic_requests
def download_file(request, file_id, type=None, file_=None, addon=None):
    """
    Download given file.

    `addon` and `file_` parameters can be passed to avoid the database query.

    If the file is disabled or belongs to an unlisted version, requires an
    add-on developer or appropriate reviewer for the channel. If the file is
    deleted or belongs to a deleted version or add-on, reviewers can still
    access but developers can't.
    """

    def is_appropriate_reviewer(addon, channel):
        return (
            acl.is_reviewer(request, addon)
            if channel == amo.RELEASE_CHANNEL_LISTED
            else acl.check_unlisted_addons_reviewer(request)
        )

    if not file_:
        file_ = get_object_or_404(File.objects, pk=file_id)
    if not addon:
        # Include deleted add-ons in the queryset, we'll check for that below.
        addon = get_object_or_404(Addon.unfiltered, pk=file_.version.addon_id)
    version = file_.version
    channel = version.channel

    if version.deleted or addon.is_deleted:
        # Only the appropriate reviewer can see deleted things.
        use_cdn = False
        has_permission = is_appropriate_reviewer(addon, channel)
    elif (
        addon.is_disabled
        or file_.status == amo.STATUS_DISABLED
        or channel == amo.RELEASE_CHANNEL_UNLISTED
    ):
        # Only the appropriate reviewer or developers of the add-on can see
        # disabled or unlisted things.
        use_cdn = False
        has_permission = is_appropriate_reviewer(
            addon, channel
        ) or acl.check_addon_ownership(request, addon, dev=True, ignore_disabled=True)
    else:
        # Everyone can see public things, and we can use the CDN in that case.
        use_cdn = True
        has_permission = True

    if not has_permission:
        log.debug(
            'download file {file_id}: addon/version/file not public and '
            'user {user_id} does not have relevant permissions.'.format(
                file_id=file_id, user_id=request.user.pk
            )
        )
        raise http.Http404()  # Not owner or admin.

    attachment = bool(type == 'attachment')
    if use_cdn:
        # When serving the file for the general public through the CDN, we need
        # to obey regional restrictions
        region_code = request.META.get('HTTP_X_COUNTRY_CODE', None)
        if (
            region_code
            and AddonRegionalRestrictions.objects.filter(
                addon=addon, excluded_regions__contains=region_code.upper()
            ).exists()
        ):
            response = http.HttpResponse(status=451)
            url = 'https://www.mozilla.org/about/policy/transparency/'
            response['Link'] = f'<{url}>; rel="blocked-by"'
        else:
            # When using the CDN URL, we do a redirect, so we can't set
            # Content-Disposition: attachment for attachments. To work around
            # this, if attachment=True, get_file_cdn_url() changes the path to
            # something we recognize in the nginx config.
            loc = urlparams(
                file_.get_file_cdn_url(attachment=attachment), filehash=file_.hash
            )
            response = http.HttpResponseRedirect(loc)
            response['X-Target-Digest'] = file_.hash
        # Always add a Vary header to deal with caching in different regions.
        patch_vary_headers(response, ['X-Country-Code'])
    else:
        # Here we're returning a X-Accel-Redirect, we can set
        # Content-Disposition: attachment ourselves in HttpResponseXSendFile:
        # nginx won't override it if present.
        response = HttpResponseXSendFile(
            request,
            file_.current_file_path,
            content_type='application/x-xpinstall',
            attachment=attachment,
        )
    response['Access-Control-Allow-Origin'] = '*'
    return response


def guard():
    return Addon.objects.filter(_current_version__isnull=False)


@addon_view_factory(guard)
@non_atomic_requests
def download_latest(request, addon, type='xpi', platform=None):
    """
    Download file from 'current' (latest public listed) version for an add-on.

    Requires same permissions as download_file() does for this file.
    """
    platforms = [amo.PLATFORM_ALL.id]
    if platform is not None and int(platform) in amo.PLATFORMS:
        platforms.append(int(platform))
    version = addon._current_version_id
    files = File.objects.filter(platform__in=platforms, version=version)
    try:
        # If there's a file matching our platform, it'll float to the end.
        file_ = sorted(files, key=lambda f: f.platform == platforms[-1])[-1]
    except IndexError:
        raise http.Http404()
    return download_file(request, file_.id, type=type, file_=file_, addon=addon)


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
    has_permission = acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN)

    if (
        addon.status != amo.STATUS_DISABLED
        and not version.files.filter(status=amo.STATUS_DISABLED).exists()
        and not version.deleted
        and not addon.is_deleted
    ):
        # Don't rely on 'admin' parameter for check_addon_ownership(), it
        # doesn't check the permission we want to check.
        has_permission = has_permission or acl.check_addon_ownership(
            request, addon, admin=False, dev=True
        )
    if not has_permission:
        raise http.Http404()

    response = HttpResponseXSendFile(request, version.source.path)
    path = version.source.path
    if not isinstance(path, str):
        path = path.decode('utf8')
    name = os.path.basename(path.replace('"', ''))
    disposition = 'attachment; filename="{0}"'.format(name).encode('utf8')
    response['Content-Disposition'] = disposition
    response['Access-Control-Allow-Origin'] = '*'
    return response
