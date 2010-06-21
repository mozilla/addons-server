from django import http
from django.shortcuts import get_object_or_404, redirect

import caching.base as caching
import jingo

import amo
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import Addon
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
