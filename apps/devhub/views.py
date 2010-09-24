import functools
import uuid

from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
import path
from tower import ugettext as _, ugettext_lazy as _lazy

import amo.utils
from amo.decorators import login_required
from access import acl
from addons.models import Addon
from addons.views import BaseFilter
from files.models import FileUpload
from . import tasks

log = commonware.log.getLogger('z.devhub')

# Acceptable extensions.
EXTENSIONS = ('.xpi', '.jar', '.xml')


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


def upload(request):
    if request.method == 'POST' and 'upload' in request.FILES:
        upload = request.FILES['upload']
        loc = path.path(settings.ADDONS_PATH) / 'temp' / uuid.uuid4().hex
        if not loc.dirname().exists():
            loc.dirname().makedirs()
        ext = path.path(upload.name).ext
        if ext in EXTENSIONS:
            loc += ext
        log.info('UPLOAD: %r (%s bytes) to %r' %
                 (upload.name, upload.size, loc))
        with open(loc, 'wb') as fd:
            for chunk in upload:
                fd.write(chunk)
        user = getattr(request, 'amo_user', None)
        fu = FileUpload.objects.create(path=loc, name=upload.name, user=user)
        task = tasks.validator.delay(fu.pk)
        return redirect('devhub.upload_detail', fu.pk)

    return jingo.render(request, 'devhub/upload.html')


def upload_detail(request, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    return jingo.render(request, 'devhub/validation.html',
                        dict(upload=upload))
