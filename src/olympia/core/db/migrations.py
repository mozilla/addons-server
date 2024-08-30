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
