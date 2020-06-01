from olympia.amo.tests import TestCase
from olympia.stats.templatetags.jinja_helpers import stats_url


class TestStatsUrl(TestCase):
    def test_with_empty_context(self):
        ctx = {}
        url = stats_url(ctx, 'stats.overview', 123)

        assert url == '/en-US/firefox/addon/123/statistics/'

    def test_with_beta_true(self):
        ctx = {'beta': True}
        url = stats_url(ctx, 'stats.overview', 123)

        assert url == '/en-US/firefox/addon/123/statistics/beta/'

    def test_with_beta_false(self):
        ctx = {'beta': False}
        url = stats_url(ctx, 'stats.overview', 123)

        assert url == '/en-US/firefox/addon/123/statistics/'
