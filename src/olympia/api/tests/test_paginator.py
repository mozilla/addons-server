from mock import MagicMock

from olympia.amo.tests import TestCase
from olympia.api.paginator import ESPaginator, Paginator


class TestSearchPaginator(TestCase):

    def test_single_hit(self):
        """Test the ESPaginator only queries ES one time."""
        mocked_qs = MagicMock()
        mocked_qs.count.return_value = 42
        paginator = Paginator(mocked_qs, 5)
        # With the base paginator, requesting any page forces a count.
        paginator.page(1)
        assert paginator.count == 42
        assert mocked_qs.count.call_count == 1

        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 666
        paginator = ESPaginator(mocked_qs, 5)
        # With the ES paginator, the count is fetched from the 'total' key
        # in the results.
        paginator.page(1)
        assert paginator.count == 666
        assert mocked_qs.count.call_count == 0
