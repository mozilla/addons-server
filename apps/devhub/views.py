import functools

from django import http
from django.shortcuts import get_object_or_404

from tower import ugettext as _, ugettext_lazy as _lazy
import jingo

import amo.utils
from amo.decorators import login_required
from access import acl
from addons.models import Addon
from addons.views import BaseFilter


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


class AddonFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


def addon_listing(request, addon_type, default='name'):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    qs = request.amo_user.addons.all()
    filter = AddonFilter(request, qs, 'sort', default)
    return filter.qs, filter


def index(request):
    return jingo.render(request, 'devhub/index.html')


@login_required
def addons_dashboard(request):
    TYPE = amo.ADDON_ANY
    addons, filter = addon_listing(request, TYPE)
    addons = amo.utils.paginate(request, addons, per_page=10)
    return jingo.render(request, 'devhub/addons/dashboard.html',
                        {'addons': addons, 'sorting': filter.field,
                         'sort_opts': filter.opts})


# TODO: If user is not a developer, redirect to url('devhub.addons').
@login_required
def addons_activity(request):
    return jingo.render(request, 'devhub/addons/activity.html')


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

    return jingo.render(request, 'devhub/addons/edit.html', data)
