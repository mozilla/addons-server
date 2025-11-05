import contextlib
import threading
from collections.abc import Mapping


_locals = threading.local()
_locals.user = None
_locals.remote_addr = None
_locals.request_metadata = None


def get_user():
    user = getattr(_locals, 'user', None)
    # The user is kept lazy, triggering no database queries until the first
    # access.
    if user and user.is_authenticated:
        return user
    return None


def set_user(user):
    _locals.user = user


def get_remote_addr():
    return getattr(_locals, 'remote_addr', None)


def set_remote_addr(remote_addr):
    _locals.remote_addr = remote_addr


def get_request_metadata():
    return getattr(_locals, 'request_metadata', None) or {}


def set_request_metadata(data):
    if data and isinstance(data, Mapping):
        _locals.request_metadata = {key: value for key, value in data.items() if value}
    else:
        _locals.request_metadata = None


def select_request_metadata(headers):
    """Get the two headers from from request.headers that we currently care about, if present.
    Note this function also normalizes the header names if it's called with request.headers
    (HttpHeaders is case-insensitive)."""
    return {
        key: val
        for key in ('Client-JA4', 'X-SigSci-Tags')
        if (val := headers.get(key)) is not None
    }


@contextlib.contextmanager
def override_remote_addr_or_metadata(*, ip_address=None, metadata=None):
    """Override value returned by get_remote_addr() for a specific context."""
    original_ip = get_remote_addr()
    original_metadata = get_request_metadata()
    if ip_address is not None:
        set_remote_addr(ip_address)
    if metadata is not None:
        set_request_metadata(metadata)
    yield
    if ip_address is not None:
        set_remote_addr(original_ip)
    if metadata is not None:
        set_request_metadata(original_metadata)
