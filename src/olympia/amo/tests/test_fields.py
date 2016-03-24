from django import forms
from django.core import exceptions

from olympia.amo.fields import SeparatedValuesField, HttpHttpsOnlyURLField
from olympia.amo.tests import TestCase


class SeparatedValuesFieldTestCase(TestCase):

    def setUp(self):
        super(SeparatedValuesFieldTestCase, self).setUp()
        self.field = SeparatedValuesField(forms.EmailField)

    def test_email_field(self):
        assert self.field.clean(u'a@b.com, c@d.com') == u'a@b.com, c@d.com'

    def test_email_field_w_empties(self):
        assert (self.field.clean(u'a@b.com,,   \n,c@d.com') ==
                u'a@b.com, c@d.com')

    def test_email_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'e')
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'a@b.com, c@d.com, e')

    def test_url_field(self):
        field = SeparatedValuesField(forms.URLField)
        assert (field.clean(u'http://hy.fr/,,http://yo.lo') ==
                u'http://hy.fr/, http://yo.lo/')

    def test_alt_separator(self):
        self.field = SeparatedValuesField(forms.EmailField, separator='#')
        assert self.field.clean(u'a@b.com#c@d.com') == u'a@b.com, c@d.com'


class HttpHttpsOnlyURLFieldTestCase(TestCase):

    def setUp(self):
        super(HttpHttpsOnlyURLFieldTestCase, self).setUp()
        self.field = HttpHttpsOnlyURLField()

    def test_invalid_scheme_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'javascript://foo.com/')

    def test_invalid_ftp_scheme_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'ftp://foo.com/')

    def test_invalid_ftps_scheme_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean(u'ftps://foo.com/')

    def test_no_scheme_assumes_http(self):
        assert self.field.clean(u'foo.com') == 'http://foo.com/'

    def test_http_scheme(self):
        assert self.field.clean(u'http://foo.com/') == u'http://foo.com/'

    def test_https_scheme(self):
        assert self.field.clean(u'https://foo.com/') == u'https://foo.com/'
