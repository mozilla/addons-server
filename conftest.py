import os

import pytest


def pytest_configure():
    # The following line is needed for all the hackery done to the python path.
    os.environ['DJANGO_SETTINGS_MODULE'] = 'settings_test'
    import manage  # noqa


@pytest.fixture(autouse=True)
def mock_inline_css(monkeypatch):
    """Mock jingo_minify.helpers.is_external: don't break on missing files.

    When testing, we don't want nor need the bundled/minified css files, so
    pretend that all the css files are external.

    Mocking this will prevent amo.helpers.inline_css to believe it should
    bundle the css.

    """
    import amo.helpers
    monkeypatch.setattr(amo.helpers, 'is_external', lambda css: True)
