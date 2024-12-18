import os
from unittest import mock


def override_env(**kwargs):
    return mock.patch.dict(os.environ, kwargs, clear=True)
