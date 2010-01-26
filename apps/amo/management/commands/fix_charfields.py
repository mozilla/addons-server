import itertools

from django.core.management.base import BaseCommand
from django.db import models, connection

qn = connection.ops.quote_name


def fix(table_name, field):
    d = {'table': table_name, 'field': qn(field.column), 'sql': sql(field)}
    update = "UPDATE {table} SET {field}='' WHERE {field} IS NULL".format(**d)
    alter = "MODIFY {sql}".format(**d)
    return update, alter


def sql(field):
    o = ['%s' % qn(field.column), field.db_type()]
    if not field.null:
        o.append('NOT NULL')
    if field.primary_key:
        o.append('PRIMARY KEY')
    if field.default is not models.fields.NOT_PROVIDED:
        o.append('default %r' % field.default)
    return ' '.join(o)


class Command(BaseCommand):
    help = 'Print SQL to change CharFields to be non-null.'
    args = '[appname ...]'

    def handle(self, *app_labels, **options):
        if app_labels:
            modules = [models.loading.get_app(app) for app in app_labels]
            models_ = itertools.chain(*[models.loading.get_models(mod)
                                        for mod in modules])
        else:
            models_ = models.loading.get_models()

        updates, alters = [], []
        for model in models_:
            model_alters = []
            table = model._meta.db_table
            for field in model._meta.fields:
                if isinstance(field, models.CharField) and not field.null:
                    update, alter = fix(table, field)
                    updates.append(update)
                    model_alters.append(alter)
            if model_alters:
                alters.append('ALTER TABLE %s\n\t%s' %
                    (table, ',\n\t'.join(model_alters)))
        print ';\n'.join(updates + alters) + ';'
