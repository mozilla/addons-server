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
        self.name = name
        super().__init__(
            delete_waffle_switch(self.name),
            reverse_code=create_waffle_switch(self.name),
            **kwargs,
        )

    def deconstruct(self):
        return (
            self.__class__.__name__,
            (self.name,),
            {},
        )

    def describe(self):
        return 'Delete Waffle Switch (Python operation)'


class CreateWaffleSwitch(migrations.RunPython):
    def __init__(self, name, **kwargs):
        self.name = name
        super().__init__(
            create_waffle_switch(self.name),
            reverse_code=delete_waffle_switch(self.name),
            **kwargs,
        )

    def deconstruct(self):
        return (
            self.__class__.__name__,
            (self.name,),
            {},
        )

    def describe(self):
        return 'Create Waffle Switch (Python operation)'


class RenameWaffleSwitch(migrations.RunPython):
    def __init__(self, old_name, new_name, **kwargs):
        self.old_name = old_name
        self.new_name = new_name
        super().__init__(
            rename_waffle_switch(self.old_name, self.new_name),
            reverse_code=rename_waffle_switch(self.new_name, self.old_name),
            **kwargs,
        )

    def deconstruct(self):
        return (
            self.__class__.__name__,
            (self.old_name, self.new_name),
            {},
        )

    def describe(self):
        return 'Rename Waffle Switch, safely (Python operation)'



class MigrationTask(migrations.RunPython):
    def __init__(self, **kwargs):
        self.func_name = 'migration_task'
        super().__init__(self.run_task, **kwargs)

    def run_task(self, apps, schema_editor):
        import importlib
        from olympia.core.tasks import migration_task

        module = importlib.import_module(self.__module__)
        try:
            breakpoint()
            func = getattr(module, self.func_name)
            migration_task.apply(func)
        except AttributeError:
            raise ValueError(f'Function {self.func_name} not found in module {self.__module__}. Create this function in the module and re-run the migration.')

    def deconstruct(self):
        return (self.__class__.__name__, (), {})


