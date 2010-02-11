from decimal import Decimal

from django.core.cache import cache
from django.core import exceptions

from nose.tools import eq_
from test_utils import ExtraAppTestCase

from amo.fields import DecimalCharField

from fieldtestapp.models import DecimalCharFieldModel


class DecimalCharFieldTestCase(ExtraAppTestCase):
    fixtures = ['fieldtestapp/test_models.json']
    extra_apps = ['amo.tests.fieldtestapp']

    def setUp(self):
        cache.clear()

    def test_fetch(self):
        o = DecimalCharFieldModel.objects.get(id=1)
        eq_(o.strict, Decimal('1.23'))
        eq_(o.loose, None)

    def test_nullify_invalid_false(self):
        val = Decimal('1.5')
        o = DecimalCharFieldModel()
        o.strict = val
        try:
            o.strict = 'not a decimal'
        except exceptions.ValidationError:
            pass
        else:
            assert False, 'invalid value did not raise an exception'
        eq_(o.strict, val, 'unexpected Decimal value')

    def test_nullify_invalid_true(self):
        val = Decimal('1.5')
        o = DecimalCharFieldModel()
        o.loose = val
        eq_(o.loose, val, 'unexpected Decimal value')

        o.loose = 'not a decimal'
        eq_(o.loose, None, 'expected None')

    def test_save(self):
        a = DecimalCharFieldModel()
        a.strict = '1.23'
        a.loose = 'this had better be NULL'
        a.save()

        b = DecimalCharFieldModel.objects.get(pk=a.id)
        eq_(b.strict, Decimal('1.23'))
        eq_(b.loose, None)
