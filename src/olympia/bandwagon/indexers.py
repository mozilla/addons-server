from operator import attrgetter

from olympia.amo.indexers import BaseSearchIndexer


class CollectionIndexer(BaseSearchIndexer):
    @classmethod
    def get_model(cls):
        from olympia.bandwagon.models import Collection
        return Collection

    @classmethod
    def get_mapping(cls):
        doc_name = cls.get_doctype_name()

        mapping = {
            doc_name: {
                'properties': {
                    'id': {'type': 'long'},

                    'app': {'type': 'byte'},
                    'boost': {'type': 'float', 'null_value': 1.0},
                    'created': {'type': 'date'},
                    'description': {'type': 'text', 'analyzer': 'snowball'},
                    'modified': {'type': 'date', 'index': False},
                    # Turn off analysis on name so we can sort by it.
                    'name_sort': {'type': 'keyword'},
                    # Adding word-delimiter to split on camelcase and
                    # punctuation.
                    'name': {'type': 'text',
                             'analyzer': 'standardPlusWordDelimiter'},
                    'type': {'type': 'byte'},
                    'slug': {'type': 'text'},

                },
            }
        }

        # Add language-specific analyzers for localized fields that are
        # analyzed/indexed.
        cls.attach_language_specific_analyzers(
            mapping, ('name', 'description'))

        return mapping

    @classmethod
    def extract_document(cls, obj):
        attrs = ('id', 'created', 'modified', 'slug', 'author_username',
                 'subscribers', 'weekly_subscribers', 'monthly_subscribers',
                 'rating', 'listed', 'type', 'application')
        data = dict(zip(attrs, attrgetter(*attrs)(obj)))
        data['app'] = data.pop('application')

        # Boost by the number of subscribers.
        data['boost'] = float(obj.subscribers ** .2)

        # Double the boost if the collection is public.
        if obj.listed:
            data['boost'] = float(max(data['boost'], 1) * 4)

        # Handle localized fields.
        for field in ('description', 'name'):
            data.update(cls.extract_field_search_translations(obj, field))
            data.update(cls.extract_field_analyzed_translations(obj, field))

        # Finally, add the special sort field, coercing the current translation
        # into an unicode object first.
        data['name_sort'] = unicode(obj.name).lower()

        return data
