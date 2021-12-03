from olympia.amo.tests import APITestClient, TestCase, reverse_ns

from ..models import Tag


class TestStaticCategoryView(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('tag-list')

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        tags = list(Tag.objects.all())

        assert len(response.data) == len(tags)

        assert response.data == [tag.tag_text for tag in tags]

    def test_cache_control(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response['cache-control'] == 'max-age=21600'
