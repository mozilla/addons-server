from django.core import exceptions

from olympia.amo.fields import HttpHttpsOnlyURLField
from olympia.amo.tests import TestCase


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
