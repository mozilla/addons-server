import StringIO
import threading

from nose.tools import eq_

from django.core import management
from django.db import connection

import amo.search
import amo.tests
from amo.urlresolvers import reverse
from amo.utils import urlparams
from es.management.commands.reindex import call_es
from lib.es.utils import is_reindexing_amo, unflag_reindexing_amo


class TestIndexCommand(amo.tests.ESTestCase):

    def setUp(self):
        super(TestIndexCommand, self).setUp()
        if is_reindexing_amo():
            unflag_reindexing_amo()

        self.url = reverse('search.search')

        # Any index created during the test will be deleted.
        self.indices = call_es('_status').json()['indices'].keys()

    def tearDown(self):
        super(TestIndexCommand, self).tearDown()
        current_indices = call_es('_status').json()['indices'].keys()
        for index in current_indices:
            if index not in self.indices:
                call_es(index, method='DELETE')

    def check_results(self, expected):
        """Make sure the expected addons are listed in a standard search."""
        response = self.client.get(urlparams(self.url, sort='downloads'))
        eq_(response.status_code, 200, str(response.content))
        got = self.get_results(response)

        for addon in expected:
            assert addon.pk in got, '%s is not in %s' % (addon.pk, got)
        return response

    def get_results(self, response):
        """Return pks of add-ons shown on search results page."""
        pager = response.context['pager']
        results = []
        for page_num in range(pager.paginator.num_pages):
            results.extend([item.pk for item
                            in pager.paginator.page(page_num + 1)])
        return results

    def get_indices_aliases(self):
        """Return the test indices with an alias."""
        indices = call_es('_aliases').json()
        items = [(index, aliases['aliases'].keys()[0])
                 for index, aliases in indices.items()
                 if len(aliases['aliases']) > 0 and index.startswith('test')]
        items.sort()
        return items

    def test_reindexation(self):
        # Adding an addon.
        addon = amo.tests.addon_factory()
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
            wanted.append(amo.tests.addon_factory())
            connection._commit()
            connection.clean_savepoints()
            amo.search.get_es().refresh()
            self.check_results(wanted)

        if len(wanted) < old_addons_count + 3:
            raise AssertionError('Could not index enough objects in foreground'
                                 ' while reindexing in the background.')

        t.join()  # Wait for the thread to finish.
        t.stdout.seek(0)
        stdout = t.stdout.read()
        assert 'Reindexation done' in stdout, stdout

        # The reindexation is done, let's double check we have all our docs.
        connection._commit()
        connection.clean_savepoints()
        amo.search.get_es().refresh()
        self.check_results(wanted)

        # New indices have been created, and aliases now point to them.
        new_indices = self.get_indices_aliases()
        eq_(len(old_indices), len(new_indices), (old_indices, new_indices))
        assert old_indices != new_indices, (stdout, old_indices, new_indices)
