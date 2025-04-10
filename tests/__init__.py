import os
from unittest import mock


def override_env(**kwargs):
    return mock.patch.dict(
        os.environ, {k: str(v) for k, v in kwargs.items()}, clear=True
    )
