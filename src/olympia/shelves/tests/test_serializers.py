from olympia.amo.tests import TestCase
from olympia.shelves.models import Shelf, ShelfManagement
from olympia.shelves.serializers import ShelfSerializer, HomepageSerializer


class TestShelvesSerializer(TestCase):
    def setUp(self):
        self.shelf = Shelf.objects.create(
            title='Populâr themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme')
        self.hpshelf = ShelfManagement.objects.create(
            position=0,
            shelf=self.shelf,
            enabled=False)

    def test_shelf_serializer(self):
        serializer = ShelfSerializer(instance=self.shelf)
        assert serializer.data == {
            'id': self.shelf.id,
            'title': 'Populâr themes',
            'endpoint': 'search',
            'criteria': '?sort=users&type=statictheme',
            'footer_text': '',
            'footer_pathname': '',
        }

    def test_homepage_serializer(self):
        serializer = HomepageSerializer(instance=self.hpshelf)
        serialized_shelf = ShelfSerializer(self.shelf).data
        assert serializer.data == {
            'shelf': serialized_shelf,
            'position': 0,
            'enabled': False
        }
