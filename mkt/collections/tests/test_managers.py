from nose.tools import ok_

import amo.tests

from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection


class TestPublicCollectionsManager(amo.tests.TestCase):

    def setUp(self):
        self.public_collection = Collection.objects.create(**{
            'name': 'Public',
            'description': 'The public one',
            'is_public': True,
            'collection_type': COLLECTIONS_TYPE_BASIC
        })
        self.private_collection = Collection.objects.create(**{
            'name': 'Private',
            'description': 'The private one',
            'is_public': False,
            'collection_type': COLLECTIONS_TYPE_BASIC
        })

    def test_public(self):
        qs = Collection.public.all()
        ok_(self.public_collection in qs)
        ok_(self.private_collection not in qs)
