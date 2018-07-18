import os

from django import http
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import (
    addon_view_factory,
    owner_or_unlisted_reviewer,
)
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, render, urlparams
from olympia.files.models import File
from olympia.versions.models import Version
from olympia.lib.cache import cache_get_or_set, make_key


# The version detail page redirects to the version within pagination, so we
# need to enforce the number of versions per page.
PER_PAGE = 30
addon_view = addon_view_factory(Addon.objects.valid)

log = olympia.core.logger.getLogger('z.versions')


def _version_list_qs(addon):
    # We only show versions that have files with the right status.
    if addon.is_unreviewed():
        status = amo.STATUS_AWAITING_REVIEW
    else:
        status = amo.STATUS_PUBLIC
    return (
        addon.versions.filter(channel=amo.RELEASE_CHANNEL_LISTED)
        .filter(files__status=status)
        .distinct()
        .order_by('-created')
    )


@addon_view
@non_atomic_requests
def version_list(request, addon):
    qs = _version_list_qs(addon)
    versions = amo.utils.paginate(request, qs, PER_PAGE)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return render(
        request,
        'versions/version_list.html',
        {'addon': addon, 'versions': versions},
    )


@addon_view
@non_atomic_requests
def version_detail(request, addon, version_num):
    # TODO: Does setting this in memcachd even make sense?
    # This is specific to an add-ons version so the chance of this hitting
    # the cache and not missing seems quite bad to me (cgrebs)
    def _fetch():
        qs = _version_list_qs(addon)
        return list(qs.values_list('version', flat=True))

    cache_key = make_key(
        u'version-detail:{}:{}'.format(addon.id, version_num), normalize=True
    )

    ids = cache_get_or_set(cache_key, _fetch)

    url = reverse('addons.versions', args=[addon.slug])
    if version_num in ids:
        page = 1 + ids.index(version_num) / PER_PAGE
        to = urlparams(url, 'version-%s' % version_num, page=page)
        return http.HttpResponseRedirect(to)
    else:
        raise http.Http404()


@addon_view
@non_atomic_requests
def update_info(request, addon, version_num):
    qs = addon.versions.filter(
        version=version_num,
        files__status__in=amo.VALID_FILE_STATUSES,
        channel=amo.RELEASE_CHANNEL_LISTED,
    )
    if not qs:
        raise http.Http404()
    return render(
        request,
        'versions/update_info.html',
        {'version': qs[0]},
        content_type='application/xhtml+xml',
    )


@non_atomic_requests
def update_info_redirect(request, version_id):
    version = get_object_or_404(Version.objects, pk=version_id)
    return redirect(
        reverse(
            'addons.versions.update_info',
            args=(version.addon.id, version.version),
        ),
        permanent=True,
    )


# Should accept junk at the end for filename goodness.
@non_atomic_requests
def download_file(request, file_id, type=None, file_=None, addon=None):
    def is_appropriate_reviewer(addon, channel):
        return (
            acl.is_reviewer(request, addon)
            if channel == amo.RELEASE_CHANNEL_LISTED
            else acl.check_unlisted_addons_reviewer(request)
        )

    if not file_:
        file_ = get_object_or_404(File.objects, pk=file_id)
    if not addon:
        addon = get_object_or_404(Addon.objects, pk=file_.version.addon_id)
    channel = file_.version.channel

    if addon.is_disabled or file_.status == amo.STATUS_DISABLED:
        if is_appropriate_reviewer(
            addon, channel
        ) or acl.check_addon_ownership(
            request, addon, dev=True, ignore_disabled=True
        ):
            return HttpResponseSendFile(
                request,
                file_.guarded_file_path,
                content_type='application/x-xpinstall',
            )
        else:
            log.info(
                u'download file {file_id}: addon/file disabled and '
                u'user {user_id} is not an owner or reviewer.'.format(
                    file_id=file_id, user_id=request.user.pk
                )
            )
            raise http.Http404()  # Not owner or admin.

    if channel == amo.RELEASE_CHANNEL_UNLISTED:
        if acl.check_unlisted_addons_reviewer(
            request
        ) or acl.check_addon_ownership(
            request, addon, dev=True, ignore_disabled=True
        ):
            return HttpResponseSendFile(
                request,
                file_.file_path,
                content_type='application/x-xpinstall',
            )
        else:
            log.info(
                u'download file {file_id}: version is unlisted and '
                u'user {user_id} is not an owner or reviewer.'.format(
                    file_id=file_id, user_id=request.user.pk
                )
            )
            raise http.Http404()  # Not owner or admin.

    attachment = type == 'attachment' or not request.APP.browser

    loc = urlparams(
        file_.get_file_cdn_url(attachment=attachment), filehash=file_.hash
    )
    response = http.HttpResponseRedirect(loc)
    response['X-Target-Digest'] = file_.hash
    return response


def guard():
    return Addon.objects.filter(_current_version__isnull=False)


@addon_view_factory(guard)
@non_atomic_requests
def download_latest(request, addon, type='xpi', platform=None):
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
    return download_file(
        request, file_.id, type=type, file_=file_, addon=addon
    )


@non_atomic_requests
def download_source(request, version_id):
    version = get_object_or_404(Version.objects, pk=version_id)

    # General case: version is listed.
    if version.channel == amo.RELEASE_CHANNEL_LISTED:
        if not (
            version.source
            and (
                acl.check_addon_ownership(
                    request, version.addon, dev=True, ignore_disabled=True
                )
            )
        ):
            raise http.Http404()
    else:
        if not owner_or_unlisted_reviewer(request, version.addon):
            raise http.Http404  # Not listed, not owner or unlisted reviewer.
    res = HttpResponseSendFile(request, version.source.path)
    path = version.source.path
    if not isinstance(path, unicode):
        path = path.decode('utf8')
    name = os.path.basename(path.replace(u'"', u''))
    disposition = u'attachment; filename="{0}"'.format(name).encode('utf8')
    res['Content-Disposition'] = disposition
    return res
