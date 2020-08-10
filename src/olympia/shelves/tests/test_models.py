from django.core.exceptions import ValidationError

from olympia.amo.tests import TestCase
from olympia.shelves.models import Shelf, ShelfManagement


class TestShelfManagement(TestCase):
    def setUp(self):
        self.shelf = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?recommended=true&sort=random&type=extension',
            footer_text='See more recommended extensions',
            footer_pathname='/this/is/the/pathname')

    def test_clean(self):
        hpshelf = ShelfManagement.objects.create(
            enabled=True,
            position=1,
            shelf=self.shelf)
        assert hpshelf.enabled
        hpshelf.enabled = True
        assert hpshelf.position == 1

    def test_clean_position_required_if_enabled(self):
        hpshelf = ShelfManagement.objects.create(
            enabled=True,
            shelf=self.shelf)
        with self.assertRaises(ValidationError) as exc:
            hpshelf.clean()
        assert exc.exception.message == (
            'Position field is required to enable shelf.')
