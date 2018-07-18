# -*- coding: utf-8 -*-
import django  # noqa

from django.db import migrations, models
from django.db.migrations.writer import MigrationWriter

import olympia  # noqa

from olympia.amo.tests import safe_exec
from olympia.translations.fields import TranslatedField


def test_translated_field_supports_migration():
    """Tests serializing translated field in a simple migration.

    Since `TranslatedField` is a ForeignKey migrations pass `to=` explicitly
    and we have to pop it in our __init__.
    """
    fields = {'charfield': TranslatedField()}

    migration = type(
        str('Migration'),
        (migrations.Migration,),
        {
            'operations': [
                migrations.CreateModel(
                    name='MyModel',
                    fields=tuple(fields.items()),
                    bases=(models.Model,),
                )
            ]
        },
    )
    writer = MigrationWriter(migration)
    output = writer.as_string()

    # Just make sure it runs and that things look alright.
    result = safe_exec(output, globals_=globals())

    assert 'Migration' in result


def test_user_foreign_key_field_deconstruct():
    field = TranslatedField(require_locale=False)
    name, path, args, kwargs = field.deconstruct()
    new_field_instance = TranslatedField(require_locale=False)

    assert kwargs['require_locale'] == new_field_instance.require_locale
    assert kwargs['to'] == new_field_instance.to
    assert kwargs['short'] == new_field_instance.short
