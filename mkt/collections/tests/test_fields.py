from django.core import exceptions

import amo.tests

from mkt.collections.fields import ColorField


class TestColorField(amo.tests.TestCase):
    def setUp(self):
        self.field = ColorField()

    def test_validation_letters_after_f(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.validate('#GGGGGG', None)

    def test_validation_too_short(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.validate('#00000', None)

    def test_validation_no_pound(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.validate('FF00FF', None)

    def should_pass(self, val):
        try:
            self.field.validate(val, None)
        except exceptions.ValidationError:
            self.fail('Value "%s" should pass validation.')

    def test_validation_passes(self):
        for value in ['#010101', '#FF00FF', '#FFFFFF']:
            self.should_pass(value)
