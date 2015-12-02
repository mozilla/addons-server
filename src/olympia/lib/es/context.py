from contextlib import contextmanager

from signals import process


@contextmanager
def send():
    yield
    process.send(None)
