import functools
import traceback

from datetime import datetime

from django import http
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.http import http_date

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import owner_or_unlisted_reviewer
from olympia.lib.cache import Token
from olympia.files.models import File
from olympia.files.file_viewer import DiffHelper, FileViewer


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


def _get_value(obj, key, value, cast=None):
    obj = getattr(obj, 'left', obj)
    key = obj.get_default(key)
    obj.select(key)
    if obj.selected:
        value = obj.selected.get(value)
        return cast(value) if cast else value


def last_modified(request, obj, key=None, **kw):
    return _get_value(obj, key, 'modified', datetime.fromtimestamp)


def etag(request, obj, key=None, **kw):
    return _get_value(obj, key, 'sha256')


def file_view(func, **kwargs):
    @functools.wraps(func)
    def wrapper(request, file_id, *args, **kw):
        file_ = get_object_or_404(File, pk=file_id)
        result = allowed(request, file_)
        if result is not True:
            return result
        try:
            obj = FileViewer(file_)
        except ObjectDoesNotExist:
            log.error('Error 404 for file %s: %s' % (
                file_id, traceback.format_exc()))
            raise http.Http404

        response = func(request, obj, *args, **kw)
        if obj.selected:
            response['ETag'] = '"%s"' % obj.selected.get('sha256')
            response['Last-Modified'] = http_date(obj.selected.get('modified'))
        return response
    return wrapper


def compare_file_view(func, **kwargs):
    @functools.wraps(func)
    def wrapper(request, one_id, two_id, *args, **kw):
        one = get_object_or_404(File, pk=one_id)
        two = get_object_or_404(File, pk=two_id)
        for obj in [one, two]:
            result = allowed(request, obj)
            if result is not True:
                return result
        try:
            obj = DiffHelper(one, two)
        except ObjectDoesNotExist:
            raise http.Http404

        response = func(request, obj, *args, **kw)
        if obj.left.selected:
            response['ETag'] = '"%s"' % obj.left.selected.get('sha256')
            response['Last-Modified'] = http_date(obj.left.selected
                                                          .get('modified'))
        return response
    return wrapper


def file_view_token(func, **kwargs):
    @functools.wraps(func)
    def wrapper(request, file_id, key, *args, **kw):
        viewer = FileViewer(get_object_or_404(File, pk=file_id))
        token = request.GET.get('token')
        if not token:
            log.error('Denying access to %s, no token.' % viewer.file.id)
            raise PermissionDenied
        if not Token.valid(token, [viewer.file.id, key]):
            log.error('Denying access to %s, token invalid.' % viewer.file.id)
            raise PermissionDenied
        return func(request, viewer, key, *args, **kw)
    return wrapper
