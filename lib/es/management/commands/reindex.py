import json
import logging
import os
import sys
import time
from optparse import make_option

from celery_tasktree import task_with_callbacks, TaskTree

import elasticsearch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from amo.search import get_es
from apps.addons import search as addons_search
from apps.stats import search as stats_search
from lib.es.utils import (is_reindexing_amo, unflag_reindexing_amo,
                          flag_reindexing_amo, timestamp_index)

logger = logging.getLogger('z.elasticsearch')

ES = get_es()


MODULES = {
    'stats': stats_search,
    'addons': addons_search,
}


def log(msg, stdout=sys.stdout):
    stdout.write(msg + '\n')


@task_with_callbacks
def delete_indexes(indexes, stdout=sys.stdout):
    indices = ','.join(indexes)
    log('Removing indices %r' % indices, stdout=stdout)
    ES.indices.delete(indices, ignore=[404, 500])


@task_with_callbacks
def update_aliases(actions, stdout=sys.stdout):
    log('Rebuilding aliases with actions: %s' % actions, stdout=stdout)
    ES.indices.update_aliases({'actions': actions}, ignore=404)


@task_with_callbacks
def create_new_index(module_str, new_index, stdout=sys.stdout):
    alias = MODULES[module_str].get_alias()
    log('Create the index {0}, for alias: {1}'.format(new_index, alias),
        stdout=stdout)

    config = {}

    # Retrieve settings from last index, if any
    if ES.indices.exists(alias):
        res = ES.indices.get_settings(alias)
        idx_settings = res.get(alias, {}).get('settings', {})
        config['number_of_replicas'] = idx_settings.get(
            'number_of_replicas',
            settings.ES_DEFAULT_NUM_REPLICAS
        )
        config['number_of_shards'] = idx_settings.get(
            'number_of_shards',
            settings.ES_DEFAULT_NUM_SHARDS
        )

    MODULES[module_str].create_new_index(new_index, config)


@task_with_callbacks
def index_data(module_str, index, stdout=sys.stdout):
    log('Reindexing {0}'.format(index), stdout=stdout)
    MODULES[module_str].reindex(index)


@task_with_callbacks
def flag_database(new_index, old_index, alias, stdout=sys.stdout):
    """Flags the database to indicate that the reindexing has started."""
    log('Flagging the database to start the reindexation', stdout=stdout)
    flag_reindexing_amo(new_index=new_index, old_index=old_index, alias=alias)


@task_with_callbacks
def unflag_database(stdout=sys.stdout):
    """Unflag the database to indicate that the reindexing is over."""
    log('Unflagging the database', stdout=stdout)
    unflag_reindexing_amo()


_SUMMARY = """
*** Reindexation done ***

Reindexed %d indexes.

Current Aliases configuration:

%s

"""


class Command(BaseCommand):
    help = 'Reindex all ES indexes'
    option_list = BaseCommand.option_list + (
        make_option('--force', action='store_true',
                    help=('Bypass the database flag that says '
                          'another indexation is ongoing'),
                    default=False),
        make_option('--wipe', action='store_true',
                    help=('Deletes AMO indexes prior to reindexing.'),
                    default=False),
        make_option('--with-stats', action='store_true',
                    help=('Whether to also reindex AMO stats. Default: False'),
                    default=False),
    )

    def handle(self, *args, **kwargs):
        """Reindexing work.

        Creates a Tasktree that creates new indexes
        over the old ones so the search feature
        works while the indexation occurs.

        """
        force = kwargs.get('force', False)

        if is_reindexing_amo() and not force:
            raise CommandError('Indexation already occuring - use --force to '
                               'bypass')

        log('Starting the reindexation', stdout=self.stdout)

        modules = ['addons']
        if kwargs.get('with_stats', False):
            modules.append('stats')

        if kwargs.get('wipe', False):
            confirm = raw_input('Are you sure you want to wipe all AMO '
                                'Elasticsearch indexes? (yes/no): ')

            while confirm not in ('yes', 'no'):
                confirm = raw_input('Please enter either "yes" or "no": ')

            if confirm == 'yes':
                unflag_database(stdout=self.stdout)
                for index in set(MODULES[m].get_alias() for m in modules):
                    ES.indices.delete(index)
            else:
                raise CommandError("Aborted.")
        elif force:
            unflag_database(stdout=self.stdout)

        alias_actions = []

        def add_alias_action(action, index, alias):
            action = {action: {'index': index, 'alias': alias}}
            if action in alias_actions:
                return
            alias_actions.append(action)

        # creating a task tree
        log('Building the task tree', stdout=self.stdout)
        tree = TaskTree()
        last_action = None

        to_remove = []

        # for each index, we create a new time-stamped index
        for module in modules:
            old_index = None
            alias = MODULES[module].get_alias()

            try:
                olds = ES.indices.get_alias(alias)
            except elasticsearch.TransportError:
                pass
            else:
                for old_index in olds.keys():
                    # mark the index to be removed later
                    to_remove.append(old_index)
                    add_alias_action('remove', old_index, alias)

            # create a new index, using the alias name with a timestamp
            new_index = timestamp_index(alias)

            # if old_index is None that could mean it's a full index
            # In that case we want to continue index in it
            if ES.indices.exists(alias):
                old_index = alias

            # flag the database
            step1 = tree.add_task(flag_database,
                                  args=[new_index, old_index, alias])
            step2 = step1.add_task(create_new_index,
                                   args=[module, new_index])
            step3 = step2.add_task(index_data,
                                   args=[module, new_index])
            last_action = step3

            # adding new index to the alias
            add_alias_action('add', new_index, alias)

        # Alias the new index and remove the old aliases, if any.
        renaming_step = last_action.add_task(update_aliases,
                                             args=[alias_actions])

        # unflag the database - there's no need to duplicate the
        # indexing anymore
        delete = renaming_step.add_task(unflag_database)

        # Delete the old indexes, if any
        if to_remove:
            delete.add_task(delete_indexes, args=[to_remove])

        # let's do it
        log('Running all indexation tasks', stdout=self.stdout)

        os.environ['FORCE_INDEXING'] = '1'
        try:
            tree.apply_async()
            if not getattr(settings, 'CELERY_ALWAYS_EAGER', False):
                time.sleep(10)   # give celeryd some time to flag the DB
            while is_reindexing_amo():
                sys.stdout.write('.')
                sys.stdout.flush()
                time.sleep(5)
        finally:
            del os.environ['FORCE_INDEXING']

        sys.stdout.write('\n')

        # let's return the /_aliases values
        aliases = ES.indices.get_aliases()
        aliases = json.dumps(aliases, sort_keys=True, indent=4)
        summary = _SUMMARY % (len(modules), aliases)
        log(summary, stdout=self.stdout)
