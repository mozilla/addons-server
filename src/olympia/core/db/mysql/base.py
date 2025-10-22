from django.db.backends.mysql import base as mysql_base


class DatabaseIntrospection(mysql_base.DatabaseIntrospection):
    def get_field_type(self, data_type, description):
        field_type = super().get_field_type(data_type, description)
        if 'auto_increment' in description.extra:
            if field_type == 'IntegerField':
                if description.is_unsigned:
                    return 'PositiveAutoField'
        return field_type


class DatabaseSchemaEditor(mysql_base.DatabaseSchemaEditor):
    def create_model(self, model):
        for field in model._meta.local_fields:
            # Autoincrement SQL for backends with post table definition variant
            if field.get_internal_type() == 'PositiveAutoField':
                autoinc_sql = self.connection.ops.autoinc_sql(
                    model._meta.db_table, field.column
                )
                if autoinc_sql:
                    self.deferred_sql.extend(autoinc_sql)
        super().create_model(model)

    def remove_field(self, model, field, algorithm=None):
        if algorithm is not None:
            self.sql_delete_column = (
                f'{self.__class__.sql_delete_column}, ALGORITHM={algorithm}'
            )
        super().remove_field(model, field)
        if algorithm is not None:
            self.sql_delete_column = self.__class__.sql_delete_column

    def add_field(self, model, field, algorithm=None):
        if algorithm is not None:
            self.sql_create_column = (
                f'{self.__class__.sql_create_column}, ALGORITHM={algorithm}'
            )
        super().add_field(model, field)
        if algorithm is not None:
            self.sql_create_column = self.__class__.sql_create_column


class DatabaseOperations(mysql_base.DatabaseOperations):
    integer_field_ranges = {
        **mysql_base.DatabaseOperations.integer_field_ranges,
        'PositiveAutoField': mysql_base.DatabaseOperations.integer_field_ranges[
            'PositiveIntegerField'
        ],
    }
    cast_data_types = {
        **mysql_base.DatabaseOperations.cast_data_types,
        'PositiveAutoField': 'unsigned integer',
    }


class DatabaseWrapper(mysql_base.DatabaseWrapper):
    introspection_class = DatabaseIntrospection
    SchemaEditorClass = DatabaseSchemaEditor
    ops_class = DatabaseOperations

    data_types = {
        **mysql_base.DatabaseWrapper.data_types,
        'PositiveAutoField': 'integer UNSIGNED AUTO_INCREMENT',
    }
