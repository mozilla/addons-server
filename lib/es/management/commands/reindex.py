import json
import logging
import os
import re
import sys
import time
import traceback
from optparse import make_option

import requests
from celery_tasktree import task_with_callbacks, TaskTree

from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from addons.cron import reindex_addons
from amo.utils import timestamp_index
from apps.addons.search import setup_mapping as put_amo_mapping
from bandwagon.cron import reindex_collections
from compat.cron import compatibility_report
from lib.es.utils import (is_reindexing_amo, unflag_reindexing_amo,
                          flag_reindexing_amo)
from stats.search import setup_indexes as put_stats_mapping
from users.cron import reindex_users


_INDEXES = {}
_ALIASES = django_settings.ES_INDEXES.copy()
# Remove stats indexes. They may be added later via the --with-stats option.
_STATS_ALIASES = {}
for k, v in _ALIASES.items():
    if 'stats' in v:
        _ALIASES.pop(k)
        _STATS_ALIASES[k] = v


def index_stats(index=None, aliased=True):
    """Indexes the previous 365 days."""
    call_command('index_stats', addons=None)


_INDEXES = {'stats': [index_stats],
            'apps': [reindex_addons,
                     reindex_collections,
                     reindex_users,
                     compatibility_report]}

logger = logging.getLogger('z.elasticsearch')
DEFAULT_NUM_REPLICAS = 0
DEFAULT_NUM_SHARDS = 3

if hasattr(django_settings, 'ES_URLS'):
    base_url = django_settings.ES_URLS[0]
else:
    base_url = 'http://127.0.0.1:9200'


def url(path):
    return '%s%s' % (base_url, path)


def _action(name, **kw):
    return {name: kw}


def call_es(path, *args, **kw):
    method = kw.pop('method', 'GET')
    status = kw.pop('status', 200)
    if isinstance(status, int):
        status = [status]

    if not path.startswith('/'):
        path = '/' + path

    method = getattr(requests, method.lower())
    res = method(url(path), *args, **kw)

    if res.status_code not in status:
        error = CommandError('Call on %r failed.\n%s' % (path, res.content))
        error.content = res.content
        error.json = res.json()
        raise error

    return res


def log(msg, stdout=sys.stdout):
    stdout.write(msg + '\n')


@task_with_callbacks
def delete_indexes(indexes, stdout=sys.stdout):
    """Removes the indexes.

    - indexes: list of indexes names to remove.
    """
    # now call the server - can we do this with a single call?
    for index in indexes:
        log('Removing index %r' % index, stdout=stdout)
        call_es(index, method='DELETE')


@task_with_callbacks
def run_aliases_actions(actions, stdout=sys.stdout):
    """Run actions on aliases.

     - action: list of action/index/alias items
    """
    # we also want to rename or delete the current index in case we have one
    dump = []
    aliases = []

    for action, index, alias in actions:
        dump.append({action: {'index': index, 'alias': alias}})

        if action == 'add':
            aliases.append(alias)

    post_data = json.dumps({'actions': dump})

    # now call the server
    log('Rebuilding aliases with actions: %s' % dump, stdout=stdout)
    try:
        call_es('_aliases', post_data, method='POST')
    except CommandError, e:
        log('Initial command error: %s' % e, stdout=stdout)
        # XXX Did not find a better way to extract the info
        error = e.json['error']
        res = re.search('(Invalid alias name \[)(?P<index>.*?)(\])', error)
        if res is None:
            raise

        index = res.groupdict()['index']
        log('Removing index %r' % index, stdout=stdout)
        call_es(index, method='DELETE')

        # Now trying again
        log('Trying again to rebuild the aliases', stdout=stdout)
        call_es('_aliases', post_data, method='POST')


@task_with_callbacks
def create_mapping(new_index, alias, num_replicas=DEFAULT_NUM_REPLICAS,
                   num_shards=DEFAULT_NUM_SHARDS, stdout=sys.stdout):
    """Creates a mapping for the new index.

    - new_index: new index name.
    - alias: alias name
    - num_replicas: number of replicas in ES
    - num_shards: number of shards in ES
    """
    log('Create the mapping for index %r, alias: %r' % (new_index, alias),
        stdout=stdout)

    if requests.head(url('/' + alias)).status_code == 200:
        res = call_es('%s/_settings' % (alias)).json()
        idx_settings = res.get(alias, {}).get('settings', {})
    else:
        idx_settings = {}

    settings = {
        'number_of_replicas': idx_settings.get('number_of_replicas',
                                               num_replicas),
        'number_of_shards': idx_settings.get('number_of_shards',
                                             num_shards)
    }

    # Create mapping without aliases since we do it manually
    if not 'stats' in alias:
        put_amo_mapping(new_index, aliased=False)
    else:
        put_stats_mapping(new_index, aliased=False)

    # Create new index
    index_url = url('/%s' % new_index)

    # if the index already exists we can keep it
    if requests.head(index_url).status_code == 200:
        return

    call_es(index_url, json.dumps(settings), method='PUT',
            status=(200, 201))


@task_with_callbacks
def create_index(index, is_stats, stdout=sys.stdout):
    """Create the index.

    - index: name of the index
    - is_stats: if True, we're indexing stats
    """
    log('Running all indexes for %r' % index, stdout=stdout)
    indexers = is_stats and _INDEXES['stats'] or _INDEXES['apps']

    for indexer in indexers:
        log('Indexing %r' % indexer.__name__, stdout=stdout)
        try:
            indexer(index, aliased=False)
        except Exception:
            # We want to log this event but continue
            log('Indexer %r failed' % indexer.__name__, stdout=stdout)
            traceback.print_exc()


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
        make_option('--prefix', action='store',
                    help='Indexes prefixes, like test_',
                    default=''),
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

        prefix = kwargs.get('prefix', '')
        log('Starting the reindexation', stdout=self.stdout)

        if kwargs.get('with_stats', False):
            # Add the stats indexes back.
            _ALIASES.update(_STATS_ALIASES)

        if kwargs.get('wipe', False):
            confirm = raw_input('Are you sure you want to wipe all AMO '
                                'Elasticsearch indexes? (yes/no): ')

            while confirm not in ('yes', 'no'):
                confirm = raw_input('Please enter either "yes" or "no": ')

            if confirm == 'yes':
                unflag_database(stdout=self.stdout)
                for index in set(_ALIASES.values()):
                    requests.delete(url('/%s') % index)
            else:
                raise CommandError("Aborted.")
        elif force:
            unflag_database(stdout=self.stdout)

        # Get list current aliases at /_aliases.
        all_aliases = requests.get(url('/_aliases')).json()

        # building the list of indexes
        indexes = set([prefix + index for index in
                       _ALIASES.values()])

        actions = []

        def add_action(*elmt):
            if elmt in actions:
                return
            actions.append(elmt)

        all_aliases = all_aliases.items()

        # creating a task tree
        log('Building the task tree', stdout=self.stdout)
        tree = TaskTree()
        last_action = None

        to_remove = []

        # for each index, we create a new time-stamped index
        for alias in indexes:
            is_stats = 'stats' in alias
            old_index = None

            for aliased_index, alias_ in all_aliases:
                if alias in alias_['aliases'].keys():
                    # mark the index to be removed later
                    old_index = aliased_index
                    to_remove.append(aliased_index)

                    # mark the alias to be removed as well
                    add_action('remove', aliased_index, alias)

            # create a new index, using the alias name with a timestamp
            new_index = timestamp_index(alias)

            # if old_index is None that could mean it's a full index
            # In that case we want to continue index in it
            future_alias = url('/%s' % alias)
            if requests.head(future_alias).status_code == 200:
                old_index = alias

            # flag the database
            step1 = tree.add_task(flag_database,
                                  args=[new_index, old_index, alias],
                                  kwargs={'stdout': self.stdout})
            step2 = step1.add_task(create_mapping,
                                   args=[new_index, alias],
                                   kwargs={'stdout': self.stdout})
            step3 = step2.add_task(create_index,
                                   args=[new_index, is_stats],
                                   kwargs={'stdout': self.stdout})
            last_action = step3

            # adding new index to the alias
            add_action('add', new_index, alias)

        # Alias the new index and remove the old aliases, if any.
        renaming_step = last_action.add_task(run_aliases_actions,
                                             args=[actions],
                                             kwargs={'stdout': self.stdout})

        # unflag the database - there's no need to duplicate the
        # indexing anymore
        delete = renaming_step.add_task(unflag_database,
                                        kwargs={'stdout': self.stdout})

        # Delete the old indexes, if any
        delete.add_task(delete_indexes,
                        args=[to_remove], kwargs={'stdout': self.stdout})

        # let's do it
        log('Running all indexation tasks', stdout=self.stdout)

        os.environ['FORCE_INDEXING'] = '1'
        try:
            tree.apply_async()
            time.sleep(10)   # give celeryd some time to flag the DB
            while is_reindexing_amo():
                sys.stdout.write('.')
                sys.stdout.flush()
                time.sleep(5)
        finally:
            del os.environ['FORCE_INDEXING']

        sys.stdout.write('\n')

        # let's return the /_aliases values
        aliases = call_es('_aliases').json()
        aliases = json.dumps(aliases, sort_keys=True, indent=4)
        summary = _SUMMARY % (len(indexes), aliases)
        log(summary, stdout=self.stdout)
