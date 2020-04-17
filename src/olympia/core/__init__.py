import contextlib
import threading


default_app_config = 'olympia.core.apps.CoreConfig'


_locals = threading.local()
_locals.user = None
_locals.remote_addr = None


def get_user():
    return getattr(_locals, 'user', None)


def set_user(user):
    _locals.user = user


def get_remote_addr():
    return getattr(_locals, 'remote_addr', None)


def set_remote_addr(remote_addr):
    _locals.remote_addr = remote_addr


@contextlib.contextmanager
def override_remote_addr(remote_addr_override):
    """Override value returned by get_remote_addr() for a specific context."""
    original = get_remote_addr()
    set_remote_addr(remote_addr_override)
    yield
    set_remote_addr(original)
