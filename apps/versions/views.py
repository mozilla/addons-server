from datetime import datetime, timedelta
import posixpath

from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.utils.encoding import smart_str

import caching.base as caching
import jingo

import amo
from amo.urlresolvers import reverse
from amo.utils import urlparams
from access import acl
from addons.models import Addon
from files.models import File
from versions.models import Version


# The version detail page redirects to the version within pagination, so we
# need to enforce the number of versions per page.
PER_PAGE = 30


def version_list(request, addon_id):
    addon = get_object_or_404(Addon.objects.valid(), pk=addon_id)
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    versions = amo.utils.paginate(request, qs, PER_PAGE)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return jingo.render(request, 'versions/version_list.html',
                        {'addon': addon, 'versions': versions})


def version_detail(request, addon_id, version_num):
    addon = get_object_or_404(Addon.objects.valid(), pk=addon_id)
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    # Use cached_with since values_list won't be cached.
    f = lambda: _find_version_page(qs, addon_id, version_num)
    return caching.cached_with(qs, f, 'vd:%s:%s' % (addon_id, version_num))


def _find_version_page(qs, addon_id, version_num):
    ids = list(qs.values_list('version', flat=True))
    url = reverse('addons.versions', args=[addon_id])
    if version_num in ids:
        page = 1 + ids.index(version_num) / PER_PAGE
        return redirect(urlparams(url, 'version-%s' % version_num, page=page))
    else:
        raise http.Http404()


# Should accept junk at the end for filename goodness.
def download_file(request, file_id, type=None):
    file = get_object_or_404(File.objects, pk=file_id)
    addon = get_object_or_404(Addon.objects.all().no_transforms(),
                              pk=file.version.addon_id)

    if (addon.status == amo.STATUS_DISABLED
        and not acl.check_ownership(request, addon)):
        raise http.Http404()

    attachment = (type == 'attachment' or not request.APP.browser)

    if file.datestatuschanged:
        published = datetime.now() - file.datestatuschanged
    else:
        published = timedelta(minutes=0)

    if attachment:
        host = posixpath.join(settings.LOCAL_MIRROR_URL, '_attachments')
    elif (addon.status == file.status == amo.STATUS_PUBLIC
          and published > timedelta(minutes=settings.MIRROR_DELAY)
          and not settings.DEBUG):
        host = settings.MIRROR_URL  # Send it to the mirrors.
    else:
        host = settings.LOCAL_MIRROR_URL
    loc = posixpath.join(*map(smart_str, [host, addon.id, file.filename]))
    response = http.HttpResponseRedirect(loc)
    response['X-Target-Digest'] = file.hash
    return response


def download_latest(request, addon_id, type='xpi', platform=None):
    addon = get_object_or_404(Addon.objects.all().no_transforms(),
                              pk=addon_id, _current_version__isnull=False)
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
    url = posixpath.join(reverse('downloads.file', args=[file.id, type]),
                         file.filename)
    if request.GET:
        url += '?' + request.GET.urlencode()
    return redirect(url)
