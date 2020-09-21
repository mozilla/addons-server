import json

from django.conf import settings

from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.models import Shelf, ShelfManagement


class TestShelfViewSet(TestCase):
    def setUp(self):
        self.url = reverse_ns('shelves-list')

        shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
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

        self.hpshelf_a = ShelfManagement.objects.create(
            shelf=shelf_a,
            position=3)
        self.hpshelf_b = ShelfManagement.objects.create(
            shelf=shelf_b,
            position=2)
        ShelfManagement.objects.create(
            shelf=shelf_c,
            position=1)

        self.search_url = reverse_ns('addon-search') + shelf_a.criteria

        self.collections_url = reverse_ns('collection-addon-list', kwargs={
            'user_pk': settings.TASK_USER_ID,
            'collection_slug': shelf_b.criteria})

    def test_no_enabled_shelves_empty_view(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'count': 0,
            'next': None,
            'page_count': 1,
            'page_size': 25,
            'previous': None,
            'results': []}

    def test_only_enabled_shelves_in_view(self):
        self.hpshelf_a.update(enabled=True)
        self.hpshelf_b.update(enabled=True)
        # don't enable shelf_c

        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)
        assert len(result['results']) == 2
        assert result['results'] == [
            {
                'title': 'Enhanced privacy extensions',
                'url': self.collections_url,
                'endpoint': 'collections',
                'criteria': 'privacy-matters',
                'footer_text': 'See more enhanced privacy extensions',
                'footer_pathname': '',
                'addons': None
            },
            {
                'title': 'Recommended extensions',
                'url': self.search_url,
                'endpoint': 'search',
                'criteria': '?promoted=recommended&sort=random&type=extension',
                'footer_text': 'See more recommended extensions',
                'footer_pathname': '',
                'addons': []
            },
        ]
