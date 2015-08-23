import pytest


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


def prefix_indexes(config):
    """Prefix all ES index names and cache keys with `test_` and, if running
    under xdist, the ID of the current slave."""

    if hasattr(config, 'slaveinput'):
        prefix = 'test_{[slaveid]}'.format(config.slaveinput)
    else:
        prefix = 'test'

    from django.conf import settings

    # Ideally, this should be a session-scoped fixture that gets injected into
    # any test that requires ES. This would be especially useful, as it would
    # allow xdist to transparently group all ES tests into a single process.
    # Unfurtunately, it's surprisingly difficult to achieve with our current
    # unittest-based setup.

    for key, index in settings.ES_INDEXES.items():
        if not index.startswith(prefix):
            settings.ES_INDEXES[key] = '{prefix}_amo_{index}'.format(
                prefix=prefix, index=index)

    settings.CACHE_PREFIX = 'amo:{0}:'.format(prefix)
    settings.KEY_PREFIX = settings.CACHE_PREFIX


def pytest_configure(config):
    prefix_indexes(config)
