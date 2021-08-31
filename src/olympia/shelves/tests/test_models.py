from olympia.amo.tests import TestCase
from olympia.tags.models import Tag

from ..models import Shelf


class TestShelfModel(TestCase):
    def test_tag_property(self):
        shelf = Shelf(endpoint=Shelf.Endpoints.RANDOM_TAG)
        assert shelf.tag is not None

        # disable all the shelves
        Tag.objects.update(enable_for_random_shelf=False)
        del shelf.tag  # Shelf.tag is a cached_property
        assert shelf.tag is None  # None because no tag available now
