from django.db import migrations


def delete_waffle_switch(name):
    def inner(apps, schema_editor):
        Switch = apps.get_model('waffle', 'Switch')
        Switch.objects.filter(name=name).delete()

    return inner


def create_waffle_switch(name):
    def inner(apps, schema_editor):
        Switch = apps.get_model('waffle', 'Switch')
        Switch.objects.get_or_create(name=name)

    return inner


def rename_waffle_switch(old_name, new_name):
    def inner(apps, schema_editor):
        Switch = apps.get_model('waffle', 'Switch')
        Switch.objects.update_or_create(name=old_name, defaults={'name': new_name})

    return inner


class DeleteWaffleSwitch(migrations.RunPython):
    def __init__(self, name, **kwargs):
        super().__init__(
            delete_waffle_switch(name),
            reverse_code=create_waffle_switch(name),
            **kwargs,
        )

    def describe(self):
        return 'Delete Waffle Switch (Python operation)'


class CreateWaffleSwitch(migrations.RunPython):
    def __init__(self, name, **kwargs):
        super().__init__(
            create_waffle_switch(name),
            reverse_code=delete_waffle_switch(name),
            **kwargs,
        )

    def describe(self):
        return 'Create Waffle Switch (Python operation)'


class RenameWaffleSwitch(migrations.RunPython):
    def __init__(self, old_name, new_name, **kwargs):
        super().__init__(
            rename_waffle_switch(old_name, new_name),
            reverse_code=rename_waffle_switch(new_name, old_name),
            **kwargs,
        )

    def describe(self):
        return 'Rename Waffle Switch, safely (Python operation)'


class RemoveFieldInstant(migrations.RemoveField):
    """A RemoveField that uses ALGORITHM=INSTANT to drop the field without row rewrites.

    See https://dev.mysql.com/doc/refman/8.4/en/innodb-online-ddl-operations.html#online-ddl-column-operations
    for more details.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        from_model = from_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, from_model):
            schema_editor.remove_field(
                from_model, from_model._meta.get_field(self.name), algorithm='INSTANT'
            )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, to_model):
            from_model = from_state.apps.get_model(app_label, self.model_name)
            schema_editor.add_field(
                from_model, to_model._meta.get_field(self.name), algorithm='INSTANT'
            )
