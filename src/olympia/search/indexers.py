import olympia.core.logger

from olympia.addons.cron import reindex_addons
from olympia.addons.indexers import AddonIndexer
from olympia.amo.indexers import BaseSearchIndexer
from olympia.compat.cron import compatibility_report
from olympia.compat.indexers import AppCompatIndexer
from olympia.lib.es.utils import create_index


log = olympia.core.logger.getLogger('z.es')


# Search-related indexers.
indexers = (AddonIndexer, AppCompatIndexer,)

# Search-related index settings.
# TODO: Is this still needed? Do we care?
# re https://github.com/mozilla/addons-server/issues/2661
# funny enough, the elasticsearch mention that `dictionary_decompounder` is to
# "decompose compound words found in many German languages"
# and all the words in the list are English... (cgrebs 042017)
INDEX_SETTINGS = {
    'similarity': {
        'default': {
            'type': 'classic'
        }
    },
    'analysis': {
        'analyzer': {
            'standardPlusWordDelimiter': {
                'tokenizer': 'standard',
                'filter': [
                    'standard', 'wordDelim', 'lowercase', 'stop', 'dict'
                ]
            }
        },
        'filter': {
            'wordDelim': {
                'type': 'word_delimiter',
                'preserve_original': True
            },
            'dict': {
                'type': 'dictionary_decompounder',
                'word_list': [
                    'cool', 'iris', 'fire', 'bug', 'flag', 'fox', 'grease',
                    'monkey', 'flash', 'block', 'forecast', 'screen', 'grab',
                    'cookie', 'auto', 'fill', 'text', 'all', 'so', 'think',
                    'mega', 'upload', 'download', 'video', 'map', 'spring',
                    'fix', 'input', 'clip', 'fly', 'lang', 'up', 'down',
                    'persona', 'css', 'html', 'http', 'ball', 'firefox',
                    'bookmark', 'chat', 'zilla', 'edit', 'menu', 'menus',
                    'status', 'bar', 'with', 'easy', 'sync', 'search',
                    'google', 'time', 'window', 'js', 'super', 'scroll',
                    'title', 'close', 'undo', 'user', 'inspect', 'inspector',
                    'browser', 'context', 'dictionary', 'mail', 'button',
                    'url', 'password', 'secure', 'image', 'new', 'tab',
                    'delete', 'click', 'name', 'smart', 'down', 'manager',
                    'open', 'query', 'net', 'link', 'blog', 'this', 'color',
                    'select', 'key', 'keys', 'foxy', 'translate', 'word',
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

    config = {
        'mappings': get_mappings(),
        'settings': {
            # create_index will add its own index settings like number of
            # shards and replicas.
            'index': INDEX_SETTINGS
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
    reindexers = [reindex_addons, compatibility_report]
    for reindexer in reindexers:
        log.info('Reindexing %r' % reindexer.__name__)
        try:
            reindexer(index_name)
        except Exception:
            # We want to log this event but continue.
            log.exception('Reindexer %r failed' % reindexer.__name__)
