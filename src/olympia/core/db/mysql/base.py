from django.db.backends.mysql.base import (
    DatabaseWrapper as MySQLDBWrapper,
    DatabaseIntrospection as MySQLDBIntrospection,
    DatabaseSchemaEditor as MySQLDBSchemeEditor)


class DatabaseIntrospection(MySQLDBIntrospection):
    def get_field_type(self, data_type, description):
        field_type = super(DatabaseIntrospection, self).get_field_type(
            data_type, description)
        if 'auto_increment' in description.extra:
            if field_type == 'IntegerField':
                if description.is_unsigned:
                    return 'PositiveAutoField'
        return field_type


class DatabaseSchemaEditor(MySQLDBSchemeEditor):
    def create_model(self, model):
        for field in model._meta.local_fields:
            # Autoincrement SQL for backends with post table definition variant
            if field.get_internal_type() == 'PositiveAutoField':
                autoinc_sql = self.connection.ops.autoinc_sql(
                    model._meta.db_table, field.column)
                if autoinc_sql:
                    self.deferred_sql.extend(autoinc_sql)
        super(DatabaseSchemaEditor, self).create_model(model)


class DatabaseWrapper(MySQLDBWrapper):
    introspection_class = DatabaseIntrospection
    SchemaEditorClass = DatabaseSchemaEditor

    # data_types is _data_types in <django2.1
    # Also replaces data_types cached_property in <django2.1 so copy over the
    # microsecond fixes as >=mysql5.6.4 is supports_microsecond_precision=True.
    data_types = dict(
        getattr(MySQLDBWrapper, '_data_types', MySQLDBWrapper.data_types),
        PositiveAutoField='integer UNSIGNED AUTO_INCREMENT',
        DateTimeField='datetime(6)',
        TimeField='time(6)')
    _data_types = data_types
