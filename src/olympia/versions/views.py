import os
import posixpath

from django import http
from django.shortcuts import get_object_or_404, redirect, render

import caching.base as caching
import commonware.log
from mobility.decorators import mobile_template

from olympia import amo
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseSendFile, urlparams
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

log = commonware.log.getLogger('z.versions')


@addon_view
@mobile_template('versions/{mobile/}version_list.html')
def version_list(request, addon, template, beta=False):
    status_list = (amo.STATUS_BETA,) if beta else amo.VALID_STATUSES
    qs = (addon.versions.filter(files__status__in=status_list)
          .distinct().order_by('-created'))
    versions = amo.utils.paginate(request, qs, PER_PAGE)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return render(request, template, {'addon': addon, 'beta': beta,
                                      'versions': versions})


@addon_view
def version_detail(request, addon, version_num):
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))

    # Use cached_with since values_list won't be cached.
    def f():
        return _find_version_page(qs, addon, version_num)

    return caching.cached_with(qs, f, 'vd:%s:%s' % (addon.id, version_num))


def _find_version_page(qs, addon, version_num):
    ids = list(qs.values_list('version', flat=True))
    url = reverse('addons.versions', args=[addon.slug])
    if version_num in ids:
        page = 1 + ids.index(version_num) / PER_PAGE
        to = urlparams(url, 'version-%s' % version_num, page=page)
        return http.HttpResponseRedirect(to)
    else:
        raise http.Http404()


@addon_view
def update_info(request, addon, version_num):
    qs = addon.versions.filter(version=version_num,
                               files__status__in=amo.VALID_STATUSES)
    if not qs:
        raise http.Http404()
    serve_xhtml = ('application/xhtml+xml' in
                   request.META.get('HTTP_ACCEPT', '').lower())
    return render(request, 'versions/update_info.html',
                  {'version': qs[0], 'serve_xhtml': serve_xhtml},
                  content_type='application/xhtml+xml')


def update_info_redirect(request, version_id):
    version = get_object_or_404(Version, pk=version_id)
    return redirect(reverse('addons.versions.update_info',
                            args=(version.addon.id, version.version)),
                    permanent=True)


# Should accept junk at the end for filename goodness.
def download_file(request, file_id, type=None):
    file = get_object_or_404(File.objects, pk=file_id)
    addon = get_object_or_404(Addon.with_unlisted, pk=file.version.addon_id)

    if addon.is_disabled or file.status == amo.STATUS_DISABLED:
        if (acl.check_addon_ownership(request, addon, viewer=True,
                                      ignore_disabled=True) or
                acl.check_addons_reviewer(request)):
            return HttpResponseSendFile(request, file.guarded_file_path,
                                        content_type='application/x-xpinstall')
        log.info(u'download file {file_id}: addon/file disabled or user '
                 u'{user_id} is not an owner'.format(file_id=file_id,
                                                     user_id=request.user.pk))
        raise http.Http404()

    if not (addon.is_listed or owner_or_unlisted_reviewer(request, addon)):
        log.info(u'download file {file_id}: addon is unlisted but user '
                 u'{user_id} is not an owner'.format(file_id=file_id,
                                                     user_id=request.user.pk))
        raise http.Http404  # Not listed, not owner or admin.

    attachment = (type == 'attachment' or not request.APP.browser)

    loc = urlparams(file.get_mirror(addon, attachment=attachment),
                    filehash=file.hash)
    response = http.HttpResponseRedirect(loc)
    response['X-Target-Digest'] = file.hash
    return response


def guard():
    return Addon.with_unlisted.filter(_current_version__isnull=False)


@addon_view_factory(guard)
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
        file = sorted(files, key=lambda f: f.platform == platforms[-1])[-1]
    except IndexError:
        raise http.Http404()
    args = [file.id, type] if type else [file.id]
    url = posixpath.join(reverse('downloads.file', args=args), file.filename)
    if request.GET:
        url += '?' + request.GET.urlencode()
    return http.HttpResponseRedirect(url)


def download_source(request, version_id):
    version = get_object_or_404(Version, pk=version_id)

    # General case: addon is listed.
    if version.addon.is_listed:
        if not (version.source and
                (acl.check_addon_ownership(request, version.addon,
                                           viewer=True, ignore_disabled=True)
                 or acl.action_allowed(request, 'Editors', 'BinarySource'))):
            raise http.Http404()
    else:
        if not owner_or_unlisted_reviewer(request, version.addon):
            raise http.Http404  # Not listed, not owner or admin.
    res = HttpResponseSendFile(request, version.source.path)
    path = version.source.path
    if not isinstance(path, unicode):
        path = path.decode('utf8')
    name = os.path.basename(path.replace(u'"', u''))
    disposition = u'attachment; filename="{0}"'.format(name).encode('utf8')
    res['Content-Disposition'] = disposition
    return res
