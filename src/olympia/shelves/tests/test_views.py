import json

from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.models import Shelf, ShelfManagement


class TestShelfViewSet(TestCase):
    def setUp(self):
        self.url = reverse_ns('shelves-list', api_version='v4')

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'count': 0,
            'next': None,
            'page_count': 1,
            'page_size': 25,
            'previous': None,
            'results': []}

        shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?recommended=true&sort=random&type=extension',
            footer_text='See more recommended extensions')
        shelf_b = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions')
        shelf_c = Shelf.objects.create(
            title='Popular themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more popular themes')

        hpshelf_a = ShelfManagement.objects.create(
            shelf=shelf_a,
            position=3)
        hpshelf_b = ShelfManagement.objects.create(
            shelf=shelf_b,
            position=2)
        ShelfManagement.objects.create(
            shelf=shelf_c,
            position=1)

        # The shelves aren't enabled so they won't show up
        response = self.client.get(self.url)
        assert response.json() == {
            'count': 0,
            'next': None,
            'page_count': 1,
            'page_size': 25,
            'previous': None,
            'results': []}

        hpshelf_a.update(enabled=True)
        hpshelf_b.update(enabled=True)
        # don't enable the last homepage shelf
        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)

        assert len(result['results']) == 2
        assert result['results'][0]['title'] == 'Enhanced privacy extensions'
        assert result['results'][1]['title'] == 'Recommended extensions'
