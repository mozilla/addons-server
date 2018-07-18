from olympia.amo.indexers import BaseSearchIndexer


class AppCompatIndexer(BaseSearchIndexer):
    @classmethod
    def get_model(cls):
        from olympia.compat.models import AppCompat

        return AppCompat

    @classmethod
    def get_mapping(cls):
        doc_name = cls.get_doctype_name()

        return {
            doc_name: {
                'properties': {
                    # We use dynamic mapping for everything for this indexer.
                }
            }
        }

    # extract_document() is not implemented because AppCompat uses its own
    # custom indexation code. See cron.py.
