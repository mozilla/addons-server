from operator import attrgetter


from olympia.amo.indexers import BaseSearchIndexer


class UserProfileIndexer(BaseSearchIndexer):
    @classmethod
    def get_model(cls):
        from olympia.users.models import UserProfile
        return UserProfile

    @classmethod
    def get_mapping(cls):
        doc_name = cls.get_doctype_name()

        return {
            doc_name: {
                'properties': {
                    # We use dynamic mapping for everything, we just need a
                    # boost field for compatibility with legacy search code.
                    'boost': {'type': 'float', 'null_value': 1.0},
                },
            },
        }

    @classmethod
    def extract_document(cls, obj):
        # These all get converted into unicode.
        unicode_attrs = ('email', 'username', 'display_name', 'biography',
                         'homepage', 'location', 'occupation')
        data = dict(zip(unicode_attrs,
                    [unicode(attr) for attr in attrgetter(*unicode_attrs)(obj)
                     if attr]))
        # These are just extracted as-is.
        attrs = ('id', 'deleted')
        data.update(dict(zip(attrs, attrgetter(*attrs)(obj))))
        return data
