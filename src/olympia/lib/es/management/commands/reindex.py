import json
import os
import sys
import time

from optparse import make_option

from celery import group
from elasticsearch.exceptions import NotFoundError

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger
from olympia.amo.search import get_es
from olympia.amo.celery import task
from olympia.search import indexers as search_indexers
from olympia.stats import search as stats_search
from olympia.lib.es.utils import (
    is_reindexing_amo, unflag_reindexing_amo, flag_reindexing_amo,
    timestamp_index)

logger = olympia.core.logger.getLogger('z.elasticsearch')
time_limits = settings.CELERY_TIME_LIMITS[
    'olympia.lib.es.management.commands.reindex']


ES = get_es()


def get_modules(with_stats=True):
    """Return python modules containing functions reindex needs.

    The `with_stats` parameter can be passed to omit the stats index module.

    This needs to be dynamic to work with testing correctly, since tests change
    the value of settings.ES_INDEXES to hit test-specific aliases."""
    rval = {
        # The keys are the index alias names, the values the python modules.
        # The 'default' in ES_INDEXES is confusingly named 'addons', but it
        # contains all the main document types we search for in AMO: addons,
        # but also collections, app compatibility, users...
        settings.ES_INDEXES['default']: search_indexers,
    }
    if with_stats:
        rval[settings.ES_INDEXES['stats']] = stats_search

    return rval


def log(msg, stdout=sys.stdout):
    stdout.write(msg + '\n')


@task
def delete_indexes(indexes, stdout=sys.stdout):
    indices = ','.join(indexes)
    log('Removing indices %r' % indices, stdout=stdout)
    ES.indices.delete(indices, ignore=[404, 500])


@task
def update_aliases(actions, stdout=sys.stdout):
    log('Rebuilding aliases with actions: %s' % actions, stdout=stdout)
    ES.indices.update_aliases({'actions': actions})


@task
def create_new_index(alias, new_index, stdout=sys.stdout):
    log('Create the index {0}, for alias: {1}'.format(new_index, alias),
        stdout=stdout)
    get_modules()[alias].create_new_index(new_index)


@task(timeout=time_limits['hard'], soft_timeout=time_limits['soft'])
def index_data(alias, index, stdout=sys.stdout):
    log('Reindexing {0}'.format(index), stdout=stdout)
    get_modules()[alias].reindex(index)


@task
def flag_database(new_index, old_index, alias, stdout=sys.stdout):
    """Flags the database to indicate that the reindexing has started."""
    log('Flagging the database to start the reindexation', stdout=stdout)
    flag_reindexing_amo(new_index=new_index, old_index=old_index, alias=alias)


@task
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
        make_option('--noinput', action='store_true',
                    help=('Do not ask for confirmation before wiping. '
                          'Default: False'),
                    default=False),
    )

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

        log('Starting the reindexation', stdout=self.stdout)

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
                unflag_database(stdout=self.stdout)
                for index in set(modules.keys()):
                    ES.indices.delete(index, ignore=404)
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

        # Creating a task chain.
        log('Building the task chain', stdout=self.stdout)

        to_remove = []
        workflow = []

        # For each alias, we create a new time-stamped index.
        for alias, module in modules.items():
            old_index = None

            try:
                olds = ES.indices.get_aliases(alias)
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

            # Flag the database.
            workflow.append(
                flag_database.si(new_index, old_index, alias) |
                create_new_index.si(alias, new_index) |
                index_data.si(alias, new_index)
            )

            # Adding new index to the alias.
            add_alias_action('add', new_index, alias)

        workflow = group(workflow)

        # Alias the new index and remove the old aliases, if any.
        workflow |= update_aliases.si(alias_actions)

        # Unflag the database - there's no need to duplicate the
        # indexing anymore.
        workflow |= unflag_database.si()

        # Delete the old indexes, if any.
        if to_remove:
            workflow |= delete_indexes.si(to_remove)

        # Let's do it.
        log('Running all indexation tasks', stdout=self.stdout)

        os.environ['FORCE_INDEXING'] = '1'

        try:
            workflow.apply_async()
            if not getattr(settings, 'CELERY_ALWAYS_EAGER', False):
                time.sleep(10)   # give celeryd some time to flag the DB
            while is_reindexing_amo():
                sys.stdout.write('.')
                sys.stdout.flush()
                time.sleep(5)
        finally:
            del os.environ['FORCE_INDEXING']

        sys.stdout.write('\n')

        # Let's return the /_aliases values.
        aliases = ES.indices.get_aliases()
        aliases = json.dumps(aliases, sort_keys=True, indent=4)
        summary = _SUMMARY % (len(modules), aliases)
        log(summary, stdout=self.stdout)
