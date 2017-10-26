import os

from django import http
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect

import caching.base as caching

import olympia.core.logger
from olympia import amo
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, urlparams, render
from olympia.access import acl
from olympia.addons.decorators import (
    addon_view_factory, owner_or_unlisted_reviewer)
from olympia.addons.models import Addon
from olympia.files.models import File
from olympia.versions.models import Version


# The version detail page redirects to the version within pagination, so we
# need to enforce the number of versions per page.
PER_PAGE = 30
addon_view = addon_view_factory(Addon.objects.valid)

log = olympia.core.logger.getLogger('z.versions')


def _version_list_qs(addon, beta=False):
    # We only show versions that have files with the right status.
    if beta:
        status = amo.STATUS_BETA
    elif addon.is_unreviewed():
        status = amo.STATUS_AWAITING_REVIEW
    else:
        status = amo.STATUS_PUBLIC
    return (addon.versions.filter(channel=amo.RELEASE_CHANNEL_LISTED)
                          .filter(files__status=status)
                          .distinct().order_by('-created'))


@addon_view
@non_atomic_requests
def version_list(request, addon, beta=False):
    qs = _version_list_qs(addon, beta=beta)
    versions = amo.utils.paginate(request, qs, PER_PAGE)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return render(request, 'versions/version_list.html', {
        'addon': addon, 'beta': beta, 'versions': versions})


@addon_view
@non_atomic_requests
def version_detail(request, addon, version_num):
    beta = amo.VERSION_BETA.search(version_num)
    qs = _version_list_qs(addon, beta=beta)

    # Use cached_with since values_list won't be cached.
    def f():
        return _find_version_page(qs, addon, version_num, beta=beta)

    return caching.cached_with(qs, f, 'vd:%s:%s' % (addon.id, version_num))


def _find_version_page(qs, addon, version_num, beta=False):
    if beta:
        url = reverse('addons.beta-versions', args=[addon.slug])
    else:
        url = reverse('addons.versions', args=[addon.slug])
    ids = list(qs.values_list('version', flat=True))
    if version_num in ids:
        page = 1 + ids.index(version_num) / PER_PAGE
        to = urlparams(url, 'version-%s' % version_num, page=page)
        return http.HttpResponseRedirect(to)
    else:
        raise http.Http404()


@addon_view
@non_atomic_requests
def update_info(request, addon, version_num):
    qs = addon.versions.filter(version=version_num,
                               files__status__in=amo.VALID_FILE_STATUSES,
                               channel=amo.RELEASE_CHANNEL_LISTED)
    if not qs:
        raise http.Http404()
    return render(request, 'versions/update_info.html',
                  {'version': qs[0]},
                  content_type='application/xhtml+xml')


@non_atomic_requests
def update_info_redirect(request, version_id):
    version = get_object_or_404(Version.objects, pk=version_id)
    return redirect(reverse('addons.versions.update_info',
                            args=(version.addon.id, version.version)),
                    permanent=True)


# Should accept junk at the end for filename goodness.
@non_atomic_requests
def download_file(request, file_id, type=None, file_=None, addon=None):
    def is_reviewer(channel):
        return (acl.check_addons_reviewer(request)
                if channel == amo.RELEASE_CHANNEL_LISTED
                else acl.check_unlisted_addons_reviewer(request))

    if not file_:
        file_ = get_object_or_404(File.objects, pk=file_id)
    if not addon:
        addon = get_object_or_404(Addon.objects,
                                  pk=file_.version.addon_id)
    channel = file_.version.channel

    if addon.is_disabled or file_.status == amo.STATUS_DISABLED:
        if is_reviewer(channel) or acl.check_addon_ownership(
                request, addon, dev=True, viewer=True, ignore_disabled=True):
            return HttpResponseSendFile(
                request, file_.guarded_file_path,
                content_type='application/x-xpinstall')
        else:
            log.info(
                u'download file {file_id}: addon/file disabled and '
                u'user {user_id} is not an owner or reviewer.'.format(
                    file_id=file_id, user_id=request.user.pk))
            raise http.Http404()  # Not owner or admin.

    if channel == amo.RELEASE_CHANNEL_UNLISTED:
        if is_reviewer(channel) or acl.check_addon_ownership(
                request, addon, dev=True, viewer=True, ignore_disabled=True):
            return HttpResponseSendFile(
                request, file_.file_path,
                content_type='application/x-xpinstall')
        else:
            log.info(
                u'download file {file_id}: version is unlisted and '
                u'user {user_id} is not an owner or reviewer.'.format(
                    file_id=file_id, user_id=request.user.pk))
            raise http.Http404()  # Not owner or admin.

    attachment = (type == 'attachment' or not request.APP.browser)

    loc = urlparams(file_.get_file_cdn_url(attachment=attachment),
                    filehash=file_.hash)
    response = http.HttpResponseRedirect(loc)
    response['X-Target-Digest'] = file_.hash
    return response


def guard():
    return Addon.objects.filter(_current_version__isnull=False)


@addon_view_factory(guard)
@non_atomic_requests
def download_latest(request, addon, beta=False, type='xpi', platform=None):
    platforms = [amo.PLATFORM_ALL.id]
    if platform is not None and int(platform) in amo.PLATFORMS:
        platforms.append(int(platform))
    if beta:
        if not addon.show_beta:
            raise http.Http404()
        version = addon.current_beta_version.id
    else:
        version = addon._current_version_id
    files = File.objects.filter(platform__in=platforms,
                                version=version)
    try:
        # If there's a file matching our platform, it'll float to the end.
        file_ = sorted(files, key=lambda f: f.platform == platforms[-1])[-1]
    except IndexError:
        raise http.Http404()
    return download_file(request, file_.id, type=type, file_=file_,
                         addon=addon)


@non_atomic_requests
def download_source(request, version_id):
    version = get_object_or_404(Version.objects, pk=version_id)

    # General case: version is listed.
    if version.channel == amo.RELEASE_CHANNEL_LISTED:
        if not (version.source and
                (acl.check_addon_ownership(
                    request, version.addon,
                    viewer=True, ignore_disabled=True))):
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
