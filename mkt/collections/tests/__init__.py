from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection


class CollectionTestMixin(object):
    collection_data = {
        'author': u'BastaCorp',
        'background_color': '#FFF000',
        'collection_type': COLLECTIONS_TYPE_BASIC,
        'description': {'en-US': u"BastaCorp's favorite HVAC apps"},
        'is_public': True,
        'name': {'en-US': u'HVAC Apps'},
        'slug': u'hvac-apps',
        'text_color': '#000FFF',
    }

    def make_collection(self, **kwargs):
        if kwargs:
            self.collection_data.update(kwargs)
        return Collection.objects.create(**self.collection_data)
