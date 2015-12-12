from decimal import Decimal

from django import forms
from django.core import exceptions
from django.db import models

from nose.tools import eq_

import amo
from amo.fields import DecimalCharField, SeparatedValuesField
import pytest


class DecimalCharFieldModel(models.Model):
    strict = DecimalCharField(max_digits=10, decimal_places=2)
    loose = DecimalCharField(max_digits=10, decimal_places=2,
                             nullify_invalid=True, null=True)


class DecimalCharFieldTestCase(amo.tests.TestCase):

    def test_basic(self):
        obj = DecimalCharFieldModel(strict='1.23', loose='foo')
        assert obj.strict == Decimal('1.23')
        assert obj.loose is None

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
        assert o.strict == val

    def test_nullify_invalid_true(self):
        val = Decimal('1.5')
        o = DecimalCharFieldModel()
        o.loose = val
        assert o.loose == val

        o.loose = 'not a decimal'
        assert o.loose is None


class SeparatedValuesFieldTestCase(amo.tests.TestCase):

    def setUp(self):
        super(SeparatedValuesFieldTestCase, self).setUp()
        self.field = SeparatedValuesField(forms.EmailField)

    def test_email_field(self):
        assert self.field.clean(u'a@b.com, c@d.com') == u'a@b.com, c@d.com'

    def test_email_field_w_empties(self):
        assert self.field.clean(u'a@b.com,,   \n,c@d.com') == u'a@b.com, c@d.com'

    def test_email_validation_error(self):
        with pytest.raises(exceptions.ValidationError):
            self.field.clean(u'e')
        with pytest.raises(exceptions.ValidationError):
            self.field.clean(u'a@b.com, c@d.com, e')

    def test_url_field(self):
        field = SeparatedValuesField(forms.URLField)
        assert field.clean(u'http://hy.fr/,,http://yo.lo') == u'http://hy.fr/, http://yo.lo/'

    def test_alt_separator(self):
        self.field = SeparatedValuesField(forms.EmailField, separator='#')
        assert self.field.clean(u'a@b.com#c@d.com') == u'a@b.com, c@d.com'
