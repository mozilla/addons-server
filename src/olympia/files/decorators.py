from django import http
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import owner_or_unlisted_reviewer


log = olympia.core.logger.getLogger('z.addons')


def allowed(request, file):
    try:
        version = file.version
        addon = version.addon
    except ObjectDoesNotExist:
        raise http.Http404

    # General case: addon is listed.
    if version.channel == amo.RELEASE_CHANNEL_LISTED:
        # We don't show the file-browser publicly because of potential DOS
        # issues, we're working on a fix but for now, let's not do this.
        # (cgrebs, 06042017)
        is_owner = acl.check_addon_ownership(request, addon, dev=True)
        if (acl.is_reviewer(request, addon) or is_owner):
            return True  # Public and sources are visible, or reviewer.
        raise PermissionDenied  # Listed but not allowed.
    # Not listed? Needs an owner or an "unlisted" admin.
    else:
        if owner_or_unlisted_reviewer(request, addon):
            return True
    raise http.Http404  # Not listed, not owner or admin.
