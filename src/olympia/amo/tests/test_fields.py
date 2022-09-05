from ipaddress import IPv4Address, IPv6Address

from django.core import exceptions
from django.db import connection, DataError
from django.test.utils import override_settings

from olympia.access.models import Group
from olympia.amo.fields import CIDRField, HttpHttpsOnlyURLField, IPAddressBinaryField
from olympia.amo.tests import TestCase


class HttpHttpsOnlyURLFieldTestCase(TestCase):

    domain = 'example.com'

    def setUp(self):
        super().setUp()

        with override_settings(DOMAIN=self.domain):
            self.field = HttpHttpsOnlyURLField()

    def test_invalid_scheme_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean('javascript://foo.com/')

    def test_invalid_ftp_scheme_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean('ftp://foo.com/')

    def test_invalid_ftps_scheme_validation_error(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean('ftps://foo.com/')

    def test_no_scheme_assumes_http(self):
        assert self.field.clean('foo.com') == 'http://foo.com'

    def test_http_scheme(self):
        assert self.field.clean('http://foo.com/') == 'http://foo.com/'

    def test_https_scheme(self):
        assert self.field.clean('https://foo.com/') == 'https://foo.com/'

    def test_catches_invalid_url(self):
        # https://github.com/mozilla/addons-server/issues/1452
        with self.assertRaises(exceptions.ValidationError):
            assert self.field.clean('https://test.[com')

    def test_with_domain_and_no_scheme(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean('%s' % self.domain)

    def test_with_domain_and_http(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean('http://%s' % self.domain)

    def test_with_domain_and_https(self):
        with self.assertRaises(exceptions.ValidationError):
            self.field.clean('https://%s' % self.domain)

    def test_domain_is_escaped_in_regex_validator(self):
        assert self.field.clean('example-com.fr') == 'http://example-com.fr'


class TestPositiveAutoField(TestCase):
    # Just using Group because it's a known user of PositiveAutoField
    ClassUsingPositiveAutoField = Group

    def test_sql_generated_for_field(self):
        schema_editor = connection.schema_editor(atomic=False)
        sql, _ = schema_editor.column_sql(
            self.ClassUsingPositiveAutoField,
            self.ClassUsingPositiveAutoField._meta.get_field('id'),
            include_default=False,
        )
        assert sql == 'integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY'

    def test_db_field_properties(self):
        table_name = self.ClassUsingPositiveAutoField._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_type, column_key, extra
                FROM information_schema.columns
                WHERE table_name='%s' and column_name='id' and
                table_schema=DATABASE();
            """
                % table_name
            )
            ((column_type, column_key, extra),) = cursor.fetchall()
            assert column_type == 'int(10) unsigned' or column_type == 'int unsigned'
            assert column_key == 'PRI'
            assert extra == 'auto_increment'

    def test_unsigned_int_limits(self):
        self.ClassUsingPositiveAutoField.objects.create(id=1)
        mysql_max_signed_int = 2147483647
        self.ClassUsingPositiveAutoField.objects.create(id=mysql_max_signed_int + 10)
        with self.assertRaises(DataError):
            self.ClassUsingPositiveAutoField.objects.create(id=-1)


class TestCIDRField(TestCase):
    def setUp(self):
        super().setUp()
        self.field = CIDRField().formfield()

    def test_validates_ip6_cidr(self):
        with self.assertRaises(exceptions.ValidationError):
            # Host bit set
            self.field.clean('::1/28')

        self.field.clean('fe80::/28')

    def test_validates_ip4_cidr(self):
        with self.assertRaises(exceptions.ValidationError):
            # Host bit set
            self.field.clean('127.0.0.1/28')

        self.field.clean('127.0.0.0/28')


class TestIPAddressBinaryField(TestCase):
    def test_from_db_value(self):
        assert IPAddressBinaryField().from_db_value(
            b'\x0f\x10\x17*', None, None
        ) == IPv4Address('15.16.23.42')

    def test_to_python(self):
        assert IPAddressBinaryField().to_python(b'\x0f\x10\x17*') == IPv4Address(
            '15.16.23.42'
        )
        assert IPAddressBinaryField().to_python('123.45.67.89') == IPv4Address(
            '123.45.67.89'
        )

        assert IPAddressBinaryField().to_python(
            b' \x01\r\xb8\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00'
        ) == IPv6Address('2001:db8::1000')
        assert IPAddressBinaryField().to_python(
            '0000:0000:0000:0000:0000:0abc:0007:0def'
        ) == IPv6Address('::abc:7:def')

        assert IPAddressBinaryField().to_python(None) is None

        with self.assertRaises(exceptions.ValidationError):
            assert IPAddressBinaryField().to_python('')
        with self.assertRaises(exceptions.ValidationError):
            assert IPAddressBinaryField().to_python('127.0.0.256')
        with self.assertRaises(exceptions.ValidationError):
            assert IPAddressBinaryField().to_python('::abc:7:def:1:99999')

    def test_get_prep_value(self):
        assert (
            IPAddressBinaryField().get_prep_value(IPv4Address('15.16.23.42'))
            == b'\x0f\x10\x17*'
        )
        assert IPAddressBinaryField().get_prep_value('15.16.23.42') == b'\x0f\x10\x17*'

        assert (
            IPAddressBinaryField().get_prep_value(IPv6Address('::abc:7:def'))
            == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\xbc\x00\x07\r\xef'
        )
        assert (
            IPAddressBinaryField().get_prep_value('::abc:7:def')
            == b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\xbc\x00\x07\r\xef'
        )

        assert IPAddressBinaryField().get_prep_value(None) is None

        with self.assertRaises(exceptions.ValidationError):
            assert IPAddressBinaryField().get_prep_value('')
        with self.assertRaises(exceptions.ValidationError):
            assert IPAddressBinaryField().get_prep_value('127.0.0.256')
