from django.shortcuts import get_object_or_404

import jingo

import amo
from addons.models import Addon
from versions.models import Version


def versions_list(request, addon_id):
    addon = get_object_or_404(Addon.objects.valid(), pk=addon_id)
    qs = (addon.versions.filter(files__status__in=amo.VALID_STATUSES)
          .distinct().order_by('-created'))
    versions = amo.utils.paginate(request, qs)
    versions.object_list = list(versions.object_list)
    Version.transformer(versions.object_list)
    return jingo.render(request, 'versions/version_list.html',
                        {'addon': addon, 'versions': versions})
