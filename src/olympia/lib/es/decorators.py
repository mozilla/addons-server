import functools

from signals import process


def send(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        res = func(*args, **kwargs)
        process.send(None)
        return res
    return wrapper
