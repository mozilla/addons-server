import functools

from django.shortcuts import get_object_or_404

from users.models import UserProfile


def profile_view(f):
    @functools.wraps(f)
    def wrapper(request, username, *args, **kw):
        """Provides a profile given either an id or username."""
        profile = get_object_or_404(UserProfile, username=username)
        return f(request, profile, *args, **kw)
    return wrapper
