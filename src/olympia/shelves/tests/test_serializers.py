from rest_framework.reverse import reverse as drf_reverse

from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.shelves.models import Shelf
from olympia.shelves.serializers import ShelfSerializer


class TestShelvesSerializer(TestCase):
    def setUp(self):
        self.shelf = Shelf.objects.create(
            title='Populâr themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more populâr themes')

    def test_shelf_serializer(self):
        serializer = ShelfSerializer(instance=self.shelf)
        assert serializer.data == {
            'title': 'Populâr themes',
            'url': (settings.INTERNAL_SITE_URL +
                    drf_reverse('v4:addon-search') +
                    self.shelf.criteria),
            'footer_text': 'See more populâr themes',
            'footer_pathname': '',
        }
