import StringIO
import threading
import time

from django.core import management
from django.db import connection
from django.test.testcases import TransactionTestCase

from olympia.amo.tests import ESTestCase, addon_factory
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.lib.es.utils import is_reindexing_amo, unflag_reindexing_amo


class TestIndexCommand(ESTestCase):
    def setUp(self):
        super(TestIndexCommand, self).setUp()
        if is_reindexing_amo():
            unflag_reindexing_amo()

        self.url = reverse('search.search')

        # We store previously existing indices in order to delete the ones
        # created during this test run.
        self.indices = self.es.indices.stats()['indices'].keys()

    # Since this test plays with transactions, but we don't have (and don't
    # really want to have) a ESTransactionTestCase class, use the fixture setup
    # and teardown methods from TransactionTestCase.
    def _fixture_setup(self):
        return TransactionTestCase._fixture_setup(self)

    def _fixture_teardown(self):
        return TransactionTestCase._fixture_teardown(self)

    def tearDown(self):
        current_indices = self.es.indices.stats()['indices'].keys()
        for index in current_indices:
            if index not in self.indices:
                self.es.indices.delete(index, ignore=404)
        super(TestIndexCommand, self).tearDown()

    def check_settings(self, new_indices):
        """Make sure the indices settings are properly set."""

        for index, alias in new_indices:
            settings = self.es.indices.get_settings(alias)[index]['settings']

            # These should be set in settings_test.
            assert int(settings['index']['number_of_replicas']) == 0
            assert int(settings['index']['number_of_shards']) == 1

    def check_results(self, expected):
        """Make sure the expected addons are listed in a standard search."""
        response = self.client.get(urlparams(self.url, sort='downloads'))
        assert response.status_code == 200
        got = self.get_results(response)

        for addon in expected:
            assert addon.pk in got, '%s is not in %s' % (addon.pk, got)
        return response

    def get_results(self, response):
        """Return pks of add-ons shown on search results page."""
        pager = response.context['pager']
        results = []
        for page_num in range(pager.paginator.num_pages):
            results.extend(
                [item.pk for item in pager.paginator.page(page_num + 1)]
            )
        return results

    @classmethod
    def get_indices_aliases(cls):
        """Return the test indices with an alias."""
        indices = cls.es.indices.get_alias()
        items = [
            (index, aliases['aliases'].keys()[0])
            for index, aliases in indices.items()
            if len(aliases['aliases']) > 0 and index.startswith('test_')
        ]
        items.sort()
        return items

    def test_reindexation(self):
        # Adding an addon.
        addon = addon_factory()
        self.refresh()

        # The search should return the addon.
        wanted = [addon]
        self.check_results(wanted)

        # Current indices with aliases.
        old_indices = self.get_indices_aliases()

        # This is to start a reindexation in the background.
        class ReindexThread(threading.Thread):
            def __init__(self):
                self.stdout = StringIO.StringIO()
                super(ReindexThread, self).__init__()

            def run(self):
                # We need to wait at least a second, to make sure the alias
                # name is going to be different, since we already create an
                # alias in setUpClass.
                time.sleep(1)
                management.call_command('reindex', stdout=self.stdout)

        t = ReindexThread()
        t.start()

        # Wait for the reindex in the thread to flag the database.
        # The database transaction isn't shared with the thread, so force the
        # commit.
        while t.is_alive() and not is_reindexing_amo():
            connection._commit()
            connection.clean_savepoints()

        # We should still be able to search in the foreground while the reindex
        # is being done in the background. We should also be able to index new
        # documents, and they should not be lost.
        old_addons_count = len(wanted)
        while t.is_alive() and len(wanted) < old_addons_count + 3:
            wanted.append(addon_factory())
            connection._commit()
            connection.clean_savepoints()
            self.refresh()
            self.check_results(wanted)

        if len(wanted) == old_addons_count:
            raise AssertionError(
                'Could not index objects in foreground while '
                'reindexing in the background.'
            )

        t.join()  # Wait for the thread to finish.
        t.stdout.seek(0)
        stdout = t.stdout.read()
        assert 'Reindexation done' in stdout, stdout

        # The reindexation is done, let's double check we have all our docs.
        connection._commit()
        connection.clean_savepoints()
        self.refresh()
        self.check_results(wanted)

        # New indices have been created, and aliases now point to them.
        new_indices = self.get_indices_aliases()
        assert len(old_indices) == len(new_indices)
        assert old_indices != new_indices, (stdout, old_indices, new_indices)

        self.check_settings(new_indices)
