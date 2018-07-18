import mock

from olympia.amo.tests import TestCase
from olympia.lib.es.models import Reindexing


class TestReindexManager(TestCase):
    def test_flag_reindexing(self):
        assert Reindexing.objects.filter(site='foo').count() == 0

        # Flagging for the first time.
        res = Reindexing.objects._flag_reindexing('foo', 'bar', 'baz', 'quux')
        assert Reindexing.objects.filter(site='foo').count() == 1
        assert res.site == 'foo'
        assert res.new_index == 'bar'
        assert res.old_index == 'baz'
        assert res.alias == 'quux'

        # Flagging for the second time.
        res = Reindexing.objects._flag_reindexing('foo', 'bar', 'baz', 'quux')
        assert Reindexing.objects.filter(site='foo').count() == 1
        assert res is None

    @mock.patch('olympia.lib.es.models.ReindexingManager._flag_reindexing')
    def test_flag_reindexing_amo(self, flag_reindexing_mock):
        Reindexing.objects.flag_reindexing_amo('bar', 'baz', 'quux')
        assert flag_reindexing_mock.called_with(
            [('amo', 'bar', 'baz', 'quux')]
        )

    def test_unflag_reindexing(self):
        assert Reindexing.objects.filter(site='foo').count() == 0

        # Unflagging unflagged database does nothing.
        Reindexing.objects._unflag_reindexing('foo')
        assert Reindexing.objects.filter(site='foo').count() == 0

        # Flag, then unflag.
        Reindexing.objects.create(
            site='foo', new_index='bar', old_index='baz', alias='quux'
        )
        assert Reindexing.objects.filter(site='foo').count() == 1

        Reindexing.objects._unflag_reindexing('foo')
        assert Reindexing.objects.filter(site='foo').count() == 0

        # Unflagging another site doesn't clash.
        Reindexing.objects.create(
            site='bar', new_index='bar', old_index='baz', alias='quux'
        )
        Reindexing.objects._unflag_reindexing('foo')
        assert Reindexing.objects.filter(site='bar').count() == 1

    @mock.patch('olympia.lib.es.models.ReindexingManager._unflag_reindexing')
    def test_unflag_reindexing_amo(self, unflag_reindexing_mock):
        Reindexing.objects.unflag_reindexing_amo()
        assert unflag_reindexing_mock.called_with([('amo')])

    def test_is_reindexing(self):
        assert Reindexing.objects.filter(site='foo').count() == 0
        assert not Reindexing.objects._is_reindexing('foo')

        Reindexing.objects.create(
            site='foo', new_index='bar', old_index='baz', alias='quux'
        )
        assert Reindexing.objects._is_reindexing('foo')

        # Reindexing on another site doesn't clash.
        assert not Reindexing.objects._is_reindexing('bar')

    @mock.patch('olympia.lib.es.models.ReindexingManager._is_reindexing')
    def test_is_reindexing_amo(self, is_reindexing_mock):
        Reindexing.objects.is_reindexing_amo()
        assert is_reindexing_mock.called_with([('amo')])

    def test_get_indices(self):
        # Not reindexing.
        assert Reindexing.objects.filter(alias='foo').count() == 0
        assert Reindexing.objects.get_indices('foo') == ['foo']

        # Reindexing on 'foo'.
        Reindexing.objects.create(
            site='foo', new_index='bar', old_index='baz', alias='quux'
        )
        assert Reindexing.objects.get_indices('quux') == ['bar', 'baz']

        # Doesn't clash on other sites.
        assert Reindexing.objects.get_indices('other') == ['other']
