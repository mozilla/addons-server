from django.db import migrations


class RenameConstraintsOperation(migrations.RunSQL):
    RENAME_FRAGMENT = "RENAME KEY `{0}` TO `{1}`"
    RENAME_FRAGMENT_REVERSE = "RENAME KEY `{1}` TO `{0}`"
    REMOVE_CLASS = migrations.RemoveConstraint
    OPERATION_PROP = 'constraint'

    def _format_renames(self, fragment, adds):
        return [
            fragment.format(old_name, getattr(operation, self.OPERATION_PROP).name)
            for operation, old_name in adds
        ]

    def _gather_state_operations(self, adds):
        state_operations = []
        for operation, old_name in adds:
            state_operations.append(operation)
            state_operations.append(
                self.REMOVE_CLASS(
                    model_name=operation.model_name,
                    name=old_name,
                )
            )
        return state_operations

    def __init__(self, table_name, adds):
        """
        `table_name` is the database table name.
        `adds` is a iterable of (<AddOperation>, <old name>) tuples.
        """
        state_operations = self._gather_state_operations(adds)

        forward_sql = f'ALTER TABLE `{table_name}` {", ".join(self._format_renames(self.RENAME_FRAGMENT, adds))}'
        reverse_sql = f'ALTER TABLE `{table_name}` {", ".join(self._format_renames(self.RENAME_FRAGMENT_REVERSE, adds))}'

        return super().__init__(
            sql=forward_sql,
            reverse_sql=reverse_sql,
            state_operations=state_operations)


class RenameIndexesOperation(RenameConstraintsOperation):
    RENAME_FRAGMENT = "RENAME INDEX `{0}` TO `{1}`"
    RENAME_FRAGMENT_REVERSE = "RENAME INDEX `{1}` TO `{0}`"
    REMOVE_CLASS = migrations.RemoveIndex
    OPERATION_PROP = 'index'
