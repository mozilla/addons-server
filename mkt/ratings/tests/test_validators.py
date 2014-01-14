from django.core.exceptions import ValidationError

import amo.tests
from mkt.ratings.validators import validate_rating


class TestValidateRating(amo.tests.TestCase):

    def test_valid(self):
        for value in [1, 2, 3, 4, 5]:
            validate_rating(value)

    def test_invalid(self):
        for value in [-4, 0, 3.5, 6]:
            with self.assertRaises(ValidationError):
                validate_rating(value)
