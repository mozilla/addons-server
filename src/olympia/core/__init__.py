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
