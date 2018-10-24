import copy

import waffle

import olympia.core.logger

from olympia.addons.cron import reindex_addons
from olympia.addons.indexers import AddonIndexer
from olympia.amo.indexers import BaseSearchIndexer
from olympia.lib.es.utils import create_index


log = olympia.core.logger.getLogger('z.es')


# Search-related indexers.
indexers = (AddonIndexer,)

# Search-related index settings.
INDEX_SETTINGS = {
    'analysis': {
        'analyzer': {
            'standardPlusWordDelimiter': {
                'tokenizer': 'standard',
                'filter': [
                    'standard', 'wordDelim', 'lowercase', 'stop', 'dict'
                ]
            }
        },
        'normalizer': {
            'lowercase_keyword_normalizer': {
                'type': 'custom',
                'filter': ['lowercase'],
            },
        },
        'filter': {
            'wordDelim': {
                'type': 'word_delimiter',
                'preserve_original': True
            },
            'dict': {
                # This filter is useful for add-on names that have multiple
                # words sticked together like "AwesomeTabPassword" for
                # instance, to help users looking for "tab password" find that
                # add-on.
                'type': 'dictionary_decompounder',
                'word_list': [
                    'all', 'auto', 'ball', 'bar', 'block', 'blog', 'bookmark',
                    'browser', 'bug', 'button', 'cat', 'chat', 'click', 'clip',
                    'close', 'color', 'context', 'cookie', 'cool', 'css',
                    'delete', 'dictionary', 'down', 'down', 'download', 'easy',
                    'edit', 'fill', 'fire', 'firefox', 'fix', 'flag', 'flash',
                    'fly', 'forecast', 'fox', 'foxy', 'google', 'grab',
                    'grease', 'html', 'http', 'image', 'input', 'inspect',
                    'inspector', 'iris', 'js', 'key', 'keys', 'lang', 'link',
                    'mail', 'manager', 'map', 'mega', 'menu', 'menus',
                    'monkey', 'name', 'net', 'new', 'open', 'password',
                    'persona', 'query', 'screen', 'scroll', 'search', 'secure',
                    'select', 'smart', 'so', 'spring', 'status', 'style',
                    'super', 'sync', 'tab', 'text', 'think', 'this', 'time',
                    'title', 'translate', 'tree', 'undo', 'up', 'upload',
                    'url', 'user', 'video', 'window', 'with', 'word', 'zilla'
                ]
            }
        }
    }
}


def create_new_index(index_name=None):
    """
    Create a new index for search-related documents in ES.

    Intended to be used by reindexation (and tests), generally a bad idea to
    call manually.
    """
    if index_name is None:
        index_name = BaseSearchIndexer.get_index_alias()

    index_settings = copy.deepcopy(INDEX_SETTINGS)

    if waffle.switch_is_active('es-use-classic-similarity'):
        # http://bit.ly/es5-similarity-module-docs
        index_settings['similarity'] = {
            'default': {
                'type': 'classic'
            }
        }

    config = {
        'mappings': get_mappings(),
        'settings': {
            # create_index will add its own index settings like number of
            # shards and replicas.
            'index': index_settings
        },
    }
    create_index(index_name, config)


def get_mappings():
    """
    Return a dict with all search-related ES mappings.
    """
    return {idxr.get_doctype_name(): idxr.get_mapping() for idxr in indexers}


def reindex(index_name):
    """
    Reindex all search-related documents on `index_name` (which is not an
    alias but the real index name).
    """
    # FIXME: refactor these reindex functions, moving them to a reindex method
    # on the indexer class, and then simply go through indexers like
    # get_mapping() does.
    reindexers = [reindex_addons]
    for reindexer in reindexers:
        log.info('Reindexing %r' % reindexer.__name__)
        try:
            reindexer(index_name)
        except Exception:
            # We want to log this event but continue.
            log.exception('Reindexer %r failed' % reindexer.__name__)
