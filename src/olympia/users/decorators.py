import functools
from six import text_type, integer_types

from django import http
from django.shortcuts import get_object_or_404

from olympia.users.models import UserProfile


def process_user_id(f):
    @functools.wraps(f)
    def wrapper(request, user_id=None, *args, **kw):
        if not user_id:
            raise http.Http404
        elif isinstance(user_id, integer_types) or user_id.isdigit():
            return f(request, int(user_id), *args, **kw)
        else:
            user = get_object_or_404(UserProfile.objects, username=user_id)
            url = request.path.replace(user_id, text_type(user.id), 1)
            if request.GET:
                url += '?' + request.GET.urlencode()
            return http.HttpResponsePermanentRedirect(url)
    return wrapper
