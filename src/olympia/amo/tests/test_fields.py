from django.core import exceptions
from django.db import connection, DataError

from olympia.access.models import Group
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
        assert self.field.clean(u'foo.com') == 'http://foo.com'

    def test_http_scheme(self):
        assert self.field.clean(u'http://foo.com/') == u'http://foo.com/'

    def test_https_scheme(self):
        assert self.field.clean(u'https://foo.com/') == u'https://foo.com/'

    def test_catches_invalid_url(self):
        # https://github.com/mozilla/addons-server/issues/1452
        with self.assertRaises(exceptions.ValidationError):
            assert self.field.clean(u'https://test.[com')


class TestPositiveAutoField(TestCase):
    # Just using Group because it's a known user of PositiveAutoField
    ClassUsingPositiveAutoField = Group

    def test_sql_generated_for_field(self):
        schema_editor = connection.schema_editor(atomic=False)
        sql, _ = schema_editor.column_sql(
            self.ClassUsingPositiveAutoField,
            self.ClassUsingPositiveAutoField._meta.get_field('id'),
            include_default=False)
        assert sql == 'integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY'

    def test_db_field_properties(self):
        table_name = self.ClassUsingPositiveAutoField._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_type, column_key, extra
                FROM information_schema.columns
                WHERE table_name='%s' and column_name='id' and
                table_schema=DATABASE();
            """ % table_name)
            (column_type, column_key, extra), = cursor.fetchall()
            assert column_type == 'int(10) unsigned'
            assert column_key == 'PRI'
            assert extra == 'auto_increment'

    def test_unsigned_int_limits(self):
        self.ClassUsingPositiveAutoField.objects.create(id=1)
        mysql_max_int_size = 4294967295
        self.ClassUsingPositiveAutoField.objects.create(id=mysql_max_int_size)
        with self.assertRaises(DataError):
            self.ClassUsingPositiveAutoField.objects.create(id=-1)
