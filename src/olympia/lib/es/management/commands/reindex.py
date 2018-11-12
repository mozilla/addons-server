import json
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from celery import group
from elasticsearch.exceptions import NotFoundError

import olympia.core.logger

from olympia.addons import indexers as addons_indexer
from olympia.amo.celery import task
from olympia.amo.search import get_es
from olympia.lib.es.utils import (
    flag_reindexing_amo, is_reindexing_amo, timestamp_index,
    unflag_reindexing_amo)
from olympia.stats import search as stats_search


logger = olympia.core.logger.getLogger('z.elasticsearch')
ES = get_es()


def get_modules(with_stats=True):
    """Return python modules containing functions reindex needs.

    The `with_stats` parameter can be passed to omit the stats index module.

    This needs to be dynamic to work with testing correctly, since tests change
    the value of settings.ES_INDEXES to hit test-specific aliases."""
    rval = {
        # The keys are the index alias names, the values the python modules.
        # The 'default' in ES_INDEXES is actually named 'addons'
        settings.ES_INDEXES['default']: addons_indexer,
    }
    if with_stats:
        rval[settings.ES_INDEXES['stats']] = stats_search

    return rval


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
    get_modules()[alias].create_new_index(new_index)


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
    return get_modules()[alias].reindex_tasks_group(index)


_SUMMARY = """
*** Reindexation done ***

Reindexed %d indexes.

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
            '--with-stats',
            action='store_true',
            help=('Whether to also reindex AMO stats. Default: False'),
            default=False),
        parser.add_argument(
            '--noinput',
            action='store_true',
            help=('Do not ask for confirmation before wiping. '
                  'Default: False'),
            default=False),

    def handle(self, *args, **kwargs):
        """Reindexing work.

        Creates a task chain that creates new indexes
        over the old ones so the search feature
        works while the indexation occurs.

        """
        force = kwargs.get('force', False)

        if is_reindexing_amo() and not force:
            raise CommandError('Indexation already occurring - use --force to '
                               'bypass')

        self.stdout.write('Starting the reindexation')

        modules = get_modules(with_stats=kwargs.get('with_stats', False))

        if kwargs.get('wipe', False):
            skip_confirmation = kwargs.get('noinput', False)
            confirm = ''
            if not skip_confirmation:
                confirm = raw_input('Are you sure you want to wipe all AMO '
                                    'Elasticsearch indexes? (yes/no): ')

                while confirm not in ('yes', 'no'):
                    confirm = raw_input('Please enter either "yes" or "no": ')

            if (confirm == 'yes' or skip_confirmation):
                unflag_database()
                for index in set(modules.keys()):
                    ES.indices.delete(index, ignore=404)
            else:
                raise CommandError("Aborted.")
        elif force:
            unflag_database()

        alias_actions = []

        def add_alias_action(action, index, alias):
            action = {action: {'index': index, 'alias': alias}}
            if action in alias_actions:
                return
            alias_actions.append(action)

        # Creating a task chain.
        self.stdout.write('Building the task chain')

        to_remove = []
        workflow = []

        # For each alias, we create a new time-stamped index.
        for alias, module in modules.items():
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

            # If old_index is None that could mean it's a full index.
            # In that case we want to continue index in it.
            if ES.indices.exists(alias):
                old_index = alias

            # Main chain for this alias: flag the database, then create the new
            # index...
            _chain = (
                flag_database.si(new_index, old_index, alias) |
                create_new_index.si(alias, new_index)
            )
            # ... Then start indexing data. gather_index_data_tasks() is a
            # function returning a group of indexing tasks.
            index_data_tasks = gather_index_data_tasks(alias, new_index)
            if index_data_tasks.tasks:
                _chain |= index_data_tasks

            # Append that chain to the workflow we're going to execute.
            workflow.append(_chain)

            # Adding new index to the alias.
            add_alias_action('add', new_index, alias)

        # Group each alias chain so that they are executed in parallel if there
        # is more than one alias to deal with.
        workflow = group(workflow)

        # Chain the global group with a task that updates the aliases to point
        # to the new indexes and remove the old aliases, if any.
        workflow |= update_aliases.si(alias_actions)

        # Chain that with a task that unflags the database - there's no need to
        # duplicate the indexing anymore.
        workflow |= unflag_database.si()

        # Finish the chain by a task that deletes the old indexes, if any.
        if to_remove:
            workflow |= delete_indexes.si(to_remove)

        # Let's do it.
        self.stdout.write('Running all indexation tasks')

        os.environ['FORCE_INDEXING'] = '1'

        try:
            workflow.apply_async()

            if not getattr(settings, 'CELERY_ALWAYS_EAGER', False):
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
        summary = _SUMMARY % (len(modules), aliases)
        self.stdout.write(summary)
