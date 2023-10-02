import io
import re
import threading
import time
from unittest import mock

from django.conf import settings
from django.core import management
from django.db import connection
from django.test.testcases import TransactionTestCase

from celery import group, shared_task
from celery.canvas import _chain

from olympia.addons.models import Addon
from olympia.amo.tests import ESTestCaseMixin, PatchMixin, addon_factory, reverse_ns
from olympia.amo.utils import urlparams
from olympia.search.management.commands import reindex
from olympia.search.models import Reindexing


@shared_task
def dummy_task():
    return None


class TestIndexCommand(ESTestCaseMixin, PatchMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        if Reindexing.objects.is_reindexing():
            Reindexing.objects.unflag_reindexing()

        self.url = reverse_ns('addon-search')

        # We store previously existing indices in order to delete the ones
        # created during this test run.
        self.indices = self.es.indices.stats()['indices'].keys()

        self.addons = []
        self.expected = self.addons[:]
        # Monkeypatch Celerys ".get()" inside async task error
        # until https://github.com/celery/celery/issues/4661 (which isn't just
        # about retries but a general regression that manifests only in
        # eager-mode) fixed.
        self.patch('celery.app.task.denied_join_result')

    def tearDown(self):
        current_indices = self.es.indices.stats()['indices'].keys()
        for index in current_indices:
            if index not in self.indices:
                self.es.indices.delete(index=index, ignore=404)
        super().tearDown()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        try:
            assert not Addon.objects.exists(), Addon.objects.values('id', 'slug')
        except AssertionError as ae:
            Addon.objects.all().delete()
            raise ae

    def check_settings(self, new_indices):
        """Make sure the indices settings are properly set."""

        for index, alias in new_indices:
            settings = self.es.indices.get_settings(index=alias)[index]['settings']

            # These should be set in settings_test.
            assert int(settings['index']['number_of_replicas']) == 0
            assert int(settings['index']['number_of_shards']) == 1

    def check_results(self, expected):
        """Make sure the expected addons are listed in a standard search."""
        response = self.client.get(urlparams(self.url, sort='downloads'))
        assert response.status_code == 200
        got = self.get_results(response)

        for addon in expected:
            assert addon.pk in got, f'{addon.pk} is not in {got}'
        return response

    def get_results(self, response):
        """Return pks of add-ons shown on search results page."""
        results = response.data['results']
        return [item['id'] for item in results]

    @classmethod
    def get_indices_aliases(cls):
        """Return the test indices with an alias."""
        indices = cls.es.indices.get_alias()
        items = [
            (index, list(aliases['aliases'].keys())[0])
            for index, aliases in indices.items()
            if len(aliases['aliases']) > 0 and index.startswith('test_')
        ]
        items.sort()
        return items

    def _test_reindexation(self, wipe=False):
        # Current indices with aliases.
        old_indices = self.get_indices_aliases()

        # This is to start a reindexation in the background.
        class ReindexThread(threading.Thread):
            def __init__(self):
                self.stdout = io.StringIO()
                super().__init__()

            def run(self):
                # We need to wait at least a second, to make sure the alias
                # name is going to be different, since we already create an
                # alias in setUpClass.
                time.sleep(1)
                management.call_command(
                    'reindex', wipe=wipe, noinput=True, stdout=self.stdout
                )

        t = ReindexThread()
        t.start()

        # Wait for the reindex in the thread to flag the database.
        # The database transaction isn't shared with the thread, so force the
        # commit.
        while t.is_alive() and not Reindexing.objects.is_reindexing():
            connection._commit()

        if not wipe:
            # We should still be able to search in the foreground while the
            # reindex is being done in the background. We should also be able
            # to index new documents, and they should not be lost.
            old_addons_count = len(self.expected)
            while t.is_alive() and len(self.expected) < old_addons_count + 3:
                self.expected.append(addon_factory())
                connection._commit()
                # We don't know where the search will happen, the reindexing
                # could be over by now. So force a refresh on *all* indices.
                self.refresh(None)
                self.check_results(self.expected)

            if len(self.expected) == old_addons_count:
                raise AssertionError(
                    'Could not index objects in foreground while reindexing '
                    'in the background. (expected: %d)' % len(self.expected)
                )

        t.join()  # Wait for the thread to finish.
        t.stdout.seek(0)
        stdout = t.stdout.read()
        assert 'Reindexation done' in stdout, stdout

        # The reindexation is done, let's double check we have all our docs.
        connection._commit()
        self.refresh()
        self.check_results(self.expected)

        # New indices have been created, and aliases now point to them.
        new_indices = self.get_indices_aliases()
        assert len(new_indices)
        assert old_indices != new_indices, (stdout, old_indices, new_indices)

        self.check_settings(new_indices)

    def test_reindexation_starting_from_zero_addons(self):
        self._test_reindexation()

    def test_reindexation_starting_from_one_addon(self):
        self.addons.append(addon_factory())
        self.expected = self.addons[:]
        self.refresh()
        self.check_results(self.expected)
        self._test_reindexation()

    def test_reindexation_with_wipe(self):
        self.addons.append(addon_factory())
        self.expected = self.addons[:]
        self.refresh()
        self.check_results(self.expected)
        self._test_reindexation(wipe=True)

    @mock.patch.object(reindex, 'gather_index_data_tasks')
    def _test_workflow(self, key, gather_index_data_tasks_mock):
        command = reindex.Command()
        alias = settings.ES_INDEXES[key]
        # Patch reindex.gather_index_data_tasks so that it returns a group of
        # dummy tasks - otherwise the chain would not contain the indexation
        # tasks (since there aren't any add-ons to index) and that's what we
        # really care about.
        gather_index_data_tasks_mock.return_value = group([dummy_task.si()] * 42)
        workflow = command.create_workflow(alias)

        # Make sure we called gather_index_data_tasks_mock with the alias and
        # timestamped index.
        expected_index = alias
        assert gather_index_data_tasks_mock.call_args[0][0] == expected_index
        assert gather_index_data_tasks_mock.call_args[0][1].startswith(expected_index)
        assert re.search('[0-9]{14}$', gather_index_data_tasks_mock.call_args[0][1])

        # Inspect workflow to make sure it contains what we expect. We should
        # have a chain with a few startup tasks, then a chord that indexes the
        # data and finishes with cleanup tasks.
        assert isinstance(workflow, _chain)

        expected_tasks = [
            'olympia.search.management.commands.reindex.create_new_index',
            'olympia.search.management.commands.reindex.flag_database',
            'celery.chord',
        ]
        assert expected_tasks == [task.name for task in workflow.tasks]

        reindex_chord = workflow.tasks[2]

        expected_header = ['olympia.search.tests.test_commands.dummy_task'] * 42
        assert expected_header == [task.name for task in reindex_chord.tasks]

        expected_body = [
            'olympia.search.management.commands.reindex.update_aliases',
            'olympia.search.management.commands.reindex.unflag_database',
        ]
        assert isinstance(reindex_chord.body, _chain)
        for i, task_name in enumerate(expected_body):
            assert task_name == reindex_chord.body.tasks[i].name
        # Note: there might be an extra task at the end of the chain to delete
        # existing indexes depending on how tests are called/set up.

    def test_create_workflow_addons(self):
        """
        Test tasks returned by create_workflow() as used by reindex command,
        for addons.
        """
        self._test_workflow('default')
