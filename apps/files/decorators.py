from datetime import datetime
import functools

from django import http
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils.http import http_date

import amo
from amo.utils import Token
from access.acl import check_addon_ownership, action_allowed
from files.helpers import DiffHelper, FileViewer
from files.models import File


def allowed(request, file):
    allowed = action_allowed(request, 'Editors', '%')

    if not allowed:
        try:
            addon = file.version.addon
        except ObjectDoesNotExist:
            return http.Http404()

        if addon.view_source and addon.status in amo.REVIEWED_STATUSES:
            allowed = True
        else:
            allowed = check_addon_ownership(request, addon,
                                            viewer=True, dev=True)
    if not allowed:
        return http.HttpResponseForbidden()
    return True


def _get_value(obj, key, value, cast=None):
    obj = getattr(obj, 'left', obj)
    key = obj.get_default(key)
    obj.select(key)
    if obj.selected:
        value = obj.selected.get(value)
        return cast(value) if cast else value


def last_modified(request, obj, key=None):
    return _get_value(obj, key, 'modified', datetime.fromtimestamp)


def etag(request, obj, key=None):
    return _get_value(obj, key, 'md5')


def file_view(func, **kwargs):
    @functools.wraps(func)
    def wrapper(request, file_id, *args, **kw):
        file = get_object_or_404(File, pk=file_id)
        result = allowed(request, file)
        if result is not True:
            return result
        obj = FileViewer(file)
        response = func(request, obj, *args, **kw)
        if obj.selected:
            response['ETag'] = '"%s"' % obj.selected.get('md5')
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
        obj = DiffHelper(one, two)
        response = func(request, obj, *args, **kw)
        if obj.left.selected:
            response['ETag'] = '"%s"' % obj.left.selected.get('md5')
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
            return http.HttpResponseForbidden()
        if not Token.valid(token, [request.META.get('REMOTE_ADDR'),
                                   viewer.file.id, key]):
            return http.HttpResponseForbidden()
        return func(request, viewer, key, *args, **kw)
    return wrapper
