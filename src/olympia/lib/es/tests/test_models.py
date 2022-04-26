from olympia.amo.tests import TestCase
from olympia.lib.es.models import Reindexing


class TestReindexManager(TestCase):
    def test_flag_reindexing(self):
        assert Reindexing.objects.count() == 0

        # Flagging for the first time.
        res = Reindexing.objects.flag_reindexing('bar', 'baz', 'quux')
        assert Reindexing.objects.count() == 1
        assert res.new_index == 'bar'
        assert res.old_index == 'baz'
        assert res.alias == 'quux'

        # Flagging for the second time.
        res = Reindexing.objects.flag_reindexing('bar', 'baz', 'quux')
        assert Reindexing.objects.count() == 1
        assert res is None

    def test_unflag_reindexing(self):
        assert Reindexing.objects.count() == 0

        # Unflagging unflagged database does nothing.
        Reindexing.objects.unflag_reindexing()
        assert Reindexing.objects.count() == 0

        # Flag, then unflag.
        Reindexing.objects.create(new_index='bar', old_index='baz', alias='quux')
        assert Reindexing.objects.count() == 1

        Reindexing.objects.unflag_reindexing()
        assert Reindexing.objects.count() == 0

    def test_is_reindexing(self):
        assert Reindexing.objects.count() == 0
        assert not Reindexing.objects.is_reindexing()

        Reindexing.objects.create(new_index='bar', old_index='baz', alias='quux')
        assert Reindexing.objects.is_reindexing()

    def test_get_indices(self):
        # Not reindexing.
        assert Reindexing.objects.filter(alias='foo').count() == 0
        assert Reindexing.objects.get_indices('foo') == ['foo']

        # Reindexing on 'foo'.
        Reindexing.objects.create(new_index='bar', old_index='baz', alias='quux')
        assert Reindexing.objects.get_indices('quux') == ['bar', 'baz']
