import json
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from elasticsearch.exceptions import NotFoundError

import olympia.core.logger

from olympia.addons.indexers import AddonIndexer
from olympia.amo.celery import task
from olympia.amo.search import get_es
from olympia.lib.es.utils import (
    flag_reindexing_amo, is_reindexing_amo, timestamp_index,
    unflag_reindexing_amo)
from olympia.stats.indexers import DownloadCountIndexer, UpdateCountIndexer


logger = olympia.core.logger.getLogger('z.elasticsearch')
ES = get_es()


def get_indexer(alias):
    """Return indexer python module for a given alias.

    This needs to be dynamic to work with testing correctly, since tests change
    the value of settings.ES_INDEXES to hit test-specific aliases.
    """
    modules = {
        # The keys are the index alias names, the values the indexer classes.
        # The 'default' in ES_INDEXES is actually named 'addons'
        settings.ES_INDEXES['default']: AddonIndexer,
        settings.ES_INDEXES['stats_download_counts']: DownloadCountIndexer,
        settings.ES_INDEXES['stats_update_counts']: UpdateCountIndexer,
    }
    return modules[alias]


@task
def delete_indexes(indexes):
    indices = ','.join(indexes)
    logger.info('Removing indices %r' % indices)
    ES.indices.delete(indices, ignore=[404, 500])


@task
def update_aliases(actions):
    logger.info('Rebuilding aliases with actions: %s' % actions)
    ES.indices.update_aliases({'actions': actions})


@task(ignore_result=False)
def create_new_index(alias, new_index):
    logger.info(
        'Create the index {0}, for alias: {1}'.format(new_index, alias))
    get_indexer(alias).create_new_index(new_index)


@task(ignore_result=False)
def flag_database(new_index, old_index, alias):
    """Flags the database to indicate that the reindexing has started."""
    logger.info('Flagging the database to start the reindexation')
    flag_reindexing_amo(new_index=new_index, old_index=old_index, alias=alias)


@task
def unflag_database():
    """Unflag the database to indicate that the reindexing is over."""
    logger.info('Unflagging the database')
    unflag_reindexing_amo()


def gather_index_data_tasks(alias, index):
    """
    Return a group of indexing tasks for that index.
    """
    logger.info('Returning reindexing group for {0}'.format(index))
    return get_indexer(alias).reindex_tasks_group(index)


_SUMMARY = """
*** Reindexation done ***

Current Aliases configuration:

%s

"""


class Command(BaseCommand):
    help = 'Reindex all ES indexes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help=('Bypass the database flag that says '
                  'another indexation is ongoing'),
            default=False),
        parser.add_argument(
            '--wipe',
            action='store_true',
            help=('Deletes AMO indexes prior to reindexing.'),
            default=False),
        parser.add_argument(
            '--key',
            action='store',
            help=(
                'Key in settings.ES_INDEXES corresponding to the alias to '
                'reindex. Can be one of the following: %s. Default is '
                '"default", which contains Add-ons data.' % (
                   self.accepted_keys()
                )
            ),
            default='default'),
        parser.add_argument(
            '--noinput',
            action='store_true',
            help=('Do not ask for confirmation before wiping. '
                  'Default: False'),
            default=False),

    def accepted_keys(self):
        return ', '.join(settings.ES_INDEXES.keys())

    def handle(self, *args, **kwargs):
        """Reindexing work.

        Creates a task chain that creates new indexes over the old ones so the
        search feature works while the indexation occurs.

        """
        force = kwargs['force']

        if is_reindexing_amo() and not force:
            raise CommandError('Indexation already occurring - use --force to '
                               'bypass')

        alias = settings.ES_INDEXES.get(kwargs['key'], None)
        if alias is None:
            raise CommandError(
                'Invalid --key parameter. It should be one of: %s.' % (
                    self.accepted_keys()
                )
            )
        self.stdout.write('Starting the reindexation for %s.' % alias)

        if kwargs['wipe']:
            skip_confirmation = kwargs['noinput']
            confirm = ''
            if not skip_confirmation:
                confirm = input('Are you sure you want to wipe all AMO '
                                'Elasticsearch indexes? (yes/no): ')

                while confirm not in ('yes', 'no'):
                    confirm = input('Please enter either "yes" or "no": ')

            if (confirm == 'yes' or skip_confirmation):
                unflag_database()
                ES.indices.delete(alias, ignore=404)
            else:
                raise CommandError('Aborted.')
        elif force:
            unflag_database()

        workflow = self.create_workflow(alias)
        self.execute_workflow(workflow)

    def create_workflow(self, alias):
        alias_actions = []

        def add_alias_action(action, index, alias):
            action = {action: {'index': index, 'alias': alias}}
            if action in alias_actions:
                return
            alias_actions.append(action)

        # Creating a task chain.
        self.stdout.write('Building the task chain')

        to_remove = []
        old_index = None

        try:
            olds = ES.indices.get_alias(alias)
            for old_index in olds:
                # Mark the index to be removed later.
                to_remove.append(old_index)
                # Mark the alias to be removed from that index.
                add_alias_action('remove', old_index, alias)
        except NotFoundError:
            # If the alias dit not exist, ignore it, don't try to remove
            # it.
            pass

        # Create a new index, using the alias name with a timestamp.
        new_index = timestamp_index(alias)
        # Mark the alias to be added at the end.
        add_alias_action('add', new_index, alias)

        # If old_index is None that could mean it's a full index.
        # In that case we want to continue index in it.
        if ES.indices.exists(alias):
            old_index = alias

        # Main chain for this alias that:
        # - creates the new index
        # - then, flags the database (which in turn makes every index call
        #   index data on both the old and the new index).
        workflow = (
            create_new_index.si(alias, new_index) |
            flag_database.si(new_index, old_index, alias)
        )
        # ... Then start indexing data. gather_index_data_tasks() is a
        # function returning a group of indexing tasks.
        index_data_tasks = gather_index_data_tasks(alias, new_index)

        if index_data_tasks.tasks:
            # Add the group to the chain, if it's not empty.
            workflow |= index_data_tasks

        # Chain with a task that updates the aliases to point to the new
        # index and remove the old aliases, if any.
        workflow |= update_aliases.si(alias_actions)

        # Chain with a task that unflags the database - there's no need to
        # duplicate the indexing anymore.
        workflow |= unflag_database.si()

        # Finish the chain by a task that deletes the old indexes, if any.
        if to_remove:
            workflow |= delete_indexes.si(to_remove)

        return workflow

    def execute_workflow(self, workflow):
        # Let's do it.
        self.stdout.write('Running all indexation tasks')

        os.environ['FORCE_INDEXING'] = '1'

        try:
            workflow.apply_async()

            if not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
                time.sleep(10)   # give celeryd some time to flag the DB
            while is_reindexing_amo():
                self.stdout.write('.')
                self.stdout.flush()
                time.sleep(5)
        finally:
            del os.environ['FORCE_INDEXING']

        self.stdout.write('\n')

        # Let's return the /_aliases values.
        aliases = ES.indices.get_alias()
        aliases = json.dumps(aliases, sort_keys=True, indent=4)
        summary = _SUMMARY % aliases
        self.stdout.write(summary)
