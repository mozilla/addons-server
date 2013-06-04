import datetime
import json
import logging
import os
import re
import sys
import time
import traceback
from optparse import make_option

import requests
from celery import chain, group, task

from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from addons.cron import reindex_addons_task
from amo.utils import timestamp_index
from apps.addons.search import setup_mapping as put_amo_mapping
from bandwagon.cron import reindex_collections_task
from compat.cron import compatibility_report_task
from lib.es.models import Reindexing
from lib.es.utils import database_flagged
from stats.search import setup_indexes as put_stats_mapping
from users.cron import reindex_users_task


_INDEXES = {}

@task(ignore_result=False)
def index_stats(index=None, aliased=True):
    """Indexes the previous 365 days."""
    call_command('index_stats', addons=None)


if django_settings.MARKETPLACE:
    # This imports marketplace stats, which then adds in the marketplace
    # inapp table. When you do that and delete an addon, the marketplace
    # then tries to delete from the non-existant table.
    #
    # This really only affects tests where the table does not exist.
    from mkt.stats.cron import index_mkt_stats_task
    from mkt.stats.search import setup_mkt_indexes as put_mkt_stats_mapping

    _INDEXES = {'stats': [index_stats.si, index_mkt_stats_task.si],
                'apps': [reindex_addons_task,
                         reindex_collections_task,
                         reindex_users_task,
                         compatibility_report_task]}

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


def log(msg):
    print msg


@task(ignore_result=False)
def delete_indexes(indexes):
    """Removes the indexes.

    - indexes: list of indexes names to remove.
    """
    # now call the server - can we do this with a single call?
    for index in indexes:
        log('Removing index %r' % index)
        call_es(index, method='DELETE')


@task(ignore_result=False)
def run_aliases_actions(actions):
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
    log('Rebuilding aliases')
    try:
        call_es('_aliases', post_data, method='POST')
    except CommandError, e:
        # XXX Did not find a better way to extract the info
        error = e.json()['error']
        res = re.search('(Invalid alias name \[)(?P<index>.*?)(\])', error)
        if res is None:
            raise

        index = res.groupdict()['index']
        log('Removing index %r' % index)
        call_es(index, method='DELETE')

        # Now trying again
        log('Trying again to rebuild the aliases')
        call_es('_aliases', post_data, method='POST')


@task(ignore_result=False)
def create_mapping(new_index, alias, num_replicas=DEFAULT_NUM_REPLICAS,
                   num_shards=DEFAULT_NUM_SHARDS):
    """Creates a mapping for the new index.

    - new_index: new index name.
    - alias: alias name
    - num_replicas: number of replicas in ES
    - num_shards: number of shards in ES
    """
    log('Create the mapping for index %r, alias: %r' % (new_index, alias))

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

    # Create mapping.without aliases since we do it manually
    if not 'stats' in alias:
        put_amo_mapping(new_index, aliased=False)
    else:
        put_stats_mapping(new_index, aliased=False)
        put_mkt_stats_mapping(new_index, aliased=False)

    # Create new index
    index_url = url('/%s' % new_index)

    # if the index already exists we can keep it
    if requests.head(index_url).status_code == 200:
        return

    call_es(index_url, json.dumps(settings), method='PUT',
            status=(200, 201))


def create_index(index, is_stats):
    """Create the index.

    - index: name of the index
    - is_stats: if True, we're indexing stats
    """
    log('Running all indexes for %r' % index)
    indexers = _INDEXES['stats' if is_stats else 'apps']
    #TODO look at task failure states? chord?
    ts = [indexer(index, aliased=False) for indexer in indexers]
    return group(ts)

@task(ignore_result=False)
def flag_database(new_index, old_index, alias):
    """Flags the database to indicate that the reindexing has started."""
    log('Flagging the database to start the reindexation')
    return Reindexing.objects.create(new_index=new_index, old_index=old_index,
                                     alias=alias,
                                     start_date=datetime.datetime.now())


@task(ignore_result=False)
def unflag_database():
    """Unflag the database to indicate that the reindexing is over."""
    log('Unflagging the database')
    Reindexing.objects.all().delete()


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
                    help=('Wipes ES from any content first. This option '
                          'will destroy anything that is in ES!'),
                    default=False),
    )

    def handle(self, *args, **kwargs):
        """Reindexing work.

        Creates a Tasktree that creates new indexes
        over the old ones so the search feature
        works while the indexation occurs
        """
        if not django_settings.MARKETPLACE:
            raise CommandError('This command affects both the marketplace and '
                               'AMO ES storage. But the command can only be '
                               'run from the Marketplace.')

        force = kwargs.get('force', False)

        if database_flagged() and not force:
            raise CommandError('Indexation already occuring - use --force to '
                               'bypass')

        prefix = kwargs.get('prefix', '')
        log('Starting the reindexation')

        if kwargs.get('wipe', False):
            confirm = raw_input("Are you sure you want to wipe all data from "
                                "ES ? (yes/no): ")

            while confirm not in ('yes', 'no'):
                confirm = raw_input('Please enter either "yes" or "no": ')

            if confirm == 'yes':
                unflag_database()
                requests.delete(url('/'))
            else:
                raise CommandError("Aborted.")
        elif force:
            unflag_database()

        # Get list current aliases at /_aliases.
        all_aliases = requests.get(url('/_aliases')).json()

        # building the list of indexes
        indexes = set([prefix + index for index in
                       django_settings.ES_INDEXES.values()])

        actions = []

        def add_action(*elmt):
            if elmt in actions:
                return
            actions.append(elmt)

        all_aliases = all_aliases.items()

        # creating a task tree
        log('Building the task tree')

        to_remove = []
        creates = []

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
            step1 = flag_database.si(new_index, old_index, alias)
            step2 = create_mapping.si(new_index, alias)
            step3 = create_index(new_index, is_stats)
            creates.append(step1 | step2 | step3)
            # adding new index to the alias
            add_action('add', new_index, alias)

        create = group(creates)
        # Alias the new index and remove the old aliases, if any.
        rename = run_aliases_actions.si(actions)

        # unflag the database - there's no need to duplicate the
        # indexing anymore
        delete = unflag_database.si()

        # Delete the old indexes, if any
        del_indexes = delete_indexes.si(to_remove)

        # let's do it
        log('Running all indexation tasks')

        os.environ['FORCE_INDEXING'] = '1'
        try:
            res = (create | rename | delete | del_indexes).apply_async()
            while not res.ready():
                sys.stdout.write('.')
                sys.stdout.flush()
                time.sleep(5)
        finally:
            del os.environ['FORCE_INDEXING']

        sys.stdout.write('\n')

        # let's return the /_aliases values
        aliases = call_es('_aliases').json()
        aliases = json.dumps(aliases, sort_keys=True, indent=4)
        return _SUMMARY % (len(indexes), aliases)
