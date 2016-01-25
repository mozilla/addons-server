from django import forms
from django.core import exceptions

from nose.tools import eq_

import amo
from amo.fields import SeparatedValuesField


class SeparatedValuesFieldTestCase(amo.tests.TestCase):

    def setUp(self):
        super(SeparatedValuesFieldTestCase, self).setUp()
        self.field = SeparatedValuesField(forms.EmailField)

    def test_email_field(self):
        eq_(self.field.clean(u'a@b.com, c@d.com'), u'a@b.com, c@d.com')

    def test_email_field_w_empties(self):
        eq_(self.field.clean(u'a@b.com,,   \n,c@d.com'), u'a@b.com, c@d.com')

    def test_email_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'e')
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'a@b.com, c@d.com, e')

    def test_url_field(self):
        field = SeparatedValuesField(forms.URLField)
        eq_(field.clean(u'http://hy.fr/,,http://yo.lo'),
            u'http://hy.fr/, http://yo.lo/')

    def test_alt_separator(self):
        self.field = SeparatedValuesField(forms.EmailField, separator='#')
        eq_(self.field.clean(u'a@b.com#c@d.com'), u'a@b.com, c@d.com')
