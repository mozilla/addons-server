from django.db import migrations, models

from ..migrations import RenameConstraintsOperation, RenameIndexesOperation


def test_rename_constraints_operation():
    add_constraint = migrations.AddConstraint(
        model_name='addoncategory',
        constraint=models.UniqueConstraint(
            fields=('addon', 'category_id'), name='addons_categories_addon_category_id'
        ),
    )
    add_constraint2 = migrations.AddConstraint(
        model_name='somemodel',
        constraint=models.UniqueConstraint(fields=('addon',), name='somename'),
    )

    op = RenameConstraintsOperation(
        'table_foo',
        [(add_constraint, 'addon_id'), (add_constraint2, 'someoldname')],
    )
    assert op.sql == (
        'ALTER TABLE `table_foo` '
        'RENAME KEY `addon_id` TO `addons_categories_addon_category_id`, '
        'RENAME KEY `someoldname` TO `somename`'
    )
    assert op.reverse_sql == (
        'ALTER TABLE `table_foo` '
        'RENAME KEY `addons_categories_addon_category_id` TO `addon_id`, '
        'RENAME KEY `somename` TO `someoldname`'
    )
    assert op.state_operations[0] == add_constraint
    assert op.state_operations[1].__class__ == migrations.RemoveConstraint
    assert op.state_operations[1].model_name == 'addoncategory'
    assert op.state_operations[1].name == 'addon_id'
    assert op.state_operations[2] == add_constraint2
    assert op.state_operations[3].__class__ == migrations.RemoveConstraint
    assert op.state_operations[3].model_name == 'somemodel'
    assert op.state_operations[3].name == 'someoldname'


def test_rename_indexes_operation():
    add_index = migrations.AddIndex(
        model_name='preview',
        index=models.Index(fields=['addon'], name='previews_addon_idx'),
    )

    add_index2 = migrations.AddIndex(
        model_name='somemodel',
        index=models.Index(fields=['addon'], name='somename'),
    )

    op = RenameIndexesOperation(
        'table_foo',
        [(add_index, 'addon_id'), (add_index2, 'someoldname')],
    )
    assert op.sql == (
        'ALTER TABLE `table_foo` '
        'RENAME INDEX `addon_id` TO `previews_addon_idx`, '
        'RENAME INDEX `someoldname` TO `somename`'
    )
    assert op.reverse_sql == (
        'ALTER TABLE `table_foo` '
        'RENAME INDEX `previews_addon_idx` TO `addon_id`, '
        'RENAME INDEX `somename` TO `someoldname`'
    )
    assert op.state_operations[0] == add_index
    assert op.state_operations[1].__class__ == migrations.RemoveIndex
    assert op.state_operations[1].model_name == 'preview'
    assert op.state_operations[1].name == 'addon_id'
    assert op.state_operations[2] == add_index2
    assert op.state_operations[3].__class__ == migrations.RemoveIndex
    assert op.state_operations[3].model_name == 'somemodel'
    assert op.state_operations[3].name == 'someoldname'
