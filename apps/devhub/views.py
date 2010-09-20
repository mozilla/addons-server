import functools

from django import http
from django.shortcuts import get_object_or_404

from tower import ugettext as _
import jingo

from amo.decorators import login_required
from access import acl
from addons.models import Addon


def owner_required(f=None, require_owner=True):
    """Requires user to be add-on owner or admin"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, addon_id, *args, **kw):
            addon = get_object_or_404(Addon, id=addon_id)
            if acl.check_addon_ownership(request, addon,
                                         require_owner=require_owner):
                return func(request, addon_id, addon, *args, **kw)
            else:
                return http.HttpResponseForbidden()
        return wrapper
    return decorator(f) if f else decorator


def index(request):
    return jingo.render(request, 'devhub/index.html', dict())


# TODO: Check if user is a developer.
@login_required
def addons_activity(request):
    return jingo.render(request, 'devhub/addons_activity.html', dict())


@login_required
@owner_required(require_owner=False)
def addons_edit(request, addon_id, addon):
    tags_dev, tags_user = addon.tags_partitioned_by_developer

    data = {
        'page': 'edit',
        'addon': addon,
        'tags_user': [tag.tag_text for tag in tags_dev],
        'tags_dev': [tag.tag_text for tag in tags_user],
        'previews': addon.previews.all(),
        }

    return jingo.render(request, 'devhub/addons_edit.html', data)
