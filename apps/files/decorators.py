import functools

from django import http
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404

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

        if addon.view_source:
            allowed = True
        else:
            allowed = check_addon_ownership(request, addon,
                                            viewer=True, dev=True)
    if not allowed:
        return http.HttpResponseForbidden()
    return True


def file_view(func, **kwargs):
    @functools.wraps(func)
    def wrapper(request, file_id, *args, **kw):
        file = get_object_or_404(File, pk=file_id)
        result = allowed(request, file)
        if result is not True:
            return result
        return func(request, FileViewer(file), *args, **kw)
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

        return func(request, DiffHelper(one, two), *args, **kw)
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
