import posixpath

from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect

import caching.base as caching
import commonware.log
import jingo
from mobility.decorators import mobile_template

import amo
from amo.urlresolvers import reverse
from amo.utils import HttpResponseSendFile, urlparams
from access import acl
from addons.decorators import addon_view_factory
from addons.models import Addon
from files.models import File
from versions.models import Version


# The version detail page redirects to the version within pagination, so we
# need to enforce the number of versions per page.
PER_PAGE = 30
addon_view = addon_view_factory(Addon.objects.valid)

log = commonware.log.getLogger('z.versions')


@addon_view
@mobile_template('versions/{mobile/}version_list.html')
def version_list(request, addon, template):
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    versions = amo.utils.paginate(request, qs, PER_PAGE)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return jingo.render(request, template,
                        {'addon': addon, 'versions': versions})


@addon_view
def version_detail(request, addon, version_num):
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    # Use cached_with since values_list won't be cached.
    f = lambda: _find_version_page(qs, addon, version_num)
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
    return jingo.render(request, 'versions/update_info.html',
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
    addon = get_object_or_404(Addon.objects, pk=file.version.addon_id)

    if addon.is_premium():
        raise PermissionDenied

    if addon.is_disabled or file.status == amo.STATUS_DISABLED:
        if (acl.check_addon_ownership(request, addon, viewer=True,
                                      ignore_disabled=True) or
            acl.check_reviewer(request)):
            return HttpResponseSendFile(request, file.guarded_file_path,
                                        content_type='application/xp-install')
        else:
            raise http.Http404()

    attachment = (type == 'attachment' or not request.APP.browser)

    loc = file.get_mirror(addon, attachment=attachment)
    response = http.HttpResponseRedirect(loc)
    response['X-Target-Digest'] = file.hash
    return response


guard = lambda: Addon.objects.filter(_current_version__isnull=False)


@addon_view_factory(guard)
def download_latest(request, addon, type='xpi', platform=None):
    platforms = [amo.PLATFORM_ALL.id]
    if platform is not None and int(platform) in amo.PLATFORMS:
        platforms.append(int(platform))
    files = File.objects.filter(platform__in=platforms,
                                version=addon._current_version_id)
    try:
        # If there's a file matching our platform, it'll float to the end.
        file = sorted(files, key=lambda f: f.platform_id == platforms[-1])[-1]
    except IndexError:
        raise http.Http404()
    args = [file.id, type] if type else [file.id]
    url = posixpath.join(reverse('downloads.file', args=args), file.filename)
    if request.GET:
        url += '?' + request.GET.urlencode()
    return http.HttpResponseRedirect(url)
