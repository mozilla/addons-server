import itertools

from django.conf import settings
from django.db import models
from django.db.models.sql import compiler

from django.utils import translation as translation_utils

import addons.query


def order_by_translation(qs, fieldname):
    """
    Order the QuerySet by the translated field, honoring the current and
    fallback locales.  Returns a new QuerySet.

    The model being sorted needs a get_fallback() classmethod that describes
    the fallback locale.  get_fallback() can return a string or a Field.
    """
    if fieldname.startswith('-'):
        desc = True
        fieldname = fieldname[1:]
    else:
        desc = False

    qs = qs.all()
    model = qs.model
    field = model._meta.get_field(fieldname)

    # (lhs, rhs, lhs_col, rhs_col) => lhs.lhs_col = rhs.rhs_col
    connection = (model._meta.db_table, field.rel.to._meta.db_table,
                  field.column, field.rel.field_name)

    # Doing the manual joins is flying under Django's radar, so we need to make
    # sure the initial alias (the main table) is set up.
    if not qs.query.tables:
        qs.query.get_initial_alias()

    # Force two LEFT JOINs against the translation table.  We'll hook up the
    # language fallbacks later.
    qs.query = qs.query.clone(TranslationQuery)
    t1 = qs.query.join(connection, always_create=True, promote=True)
    t2 = qs.query.join(connection, always_create=True, promote=True)
    qs.query.translation_aliases = {field: (t1, t2)}

    f1, f2 = '%s.`localized_string`' % t1, '%s.`localized_string`' % t2
    name = 'translated_%s' % field.column
    ifnull = 'IFNULL(%s, %s)' % (f1, f2)
    prefix = '-' if desc else ''
    return qs.extra(select={name: ifnull},
                    where=['(%s IS NOT NULL OR %s IS NOT NULL)' % (f1, f2)],
                    order_by=[prefix + name])


class TranslationQuery(addons.query.IndexQuery):
    """
    Overrides sql.Query to hit our special compiler that knows how to JOIN
    translations.
    """

    def clone(self, klass=None, **kwargs):
        # Maintain translation_aliases across clones.
        c = super(TranslationQuery, self).clone(klass, **kwargs)
        c.translation_aliases = self.translation_aliases
        return c

    def get_compiler(self, using=None, connection=None):
        # Call super to figure out using and connection.
        c = super(TranslationQuery, self).get_compiler(using, connection)
        return SQLCompiler(self, c.connection, c.using)


class SQLCompiler(addons.query.IndexCompiler):
    """Overrides get_from_clause to LEFT JOIN translations with a locale."""

    def get_from_clause(self):
        # Temporarily remove translation tables from query.tables so Django
        # doesn't create joins against them.
        old_tables = list(self.query.tables)
        for table in itertools.chain(*self.query.translation_aliases.values()):
            self.query.tables.remove(table)

        joins, params = super(SQLCompiler, self).get_from_clause()

        # fallback could be a string locale or a model field.
        params.append(translation_utils.get_language())
        if hasattr(self.query.model, 'get_fallback'):
            fallback = self.query.model.get_fallback()
        else:
            fallback = settings.LANGUAGE_CODE
        if not isinstance(fallback, models.Field):
            params.append(fallback)

        # Add our locale-aware joins.  We're not respecting the table ordering
        # Django had in query.tables, but that seems to be ok.
        for field, aliases in self.query.translation_aliases.items():
            t1, t2 = aliases
            joins.append(self.join_with_locale(t1))
            joins.append(self.join_with_locale(t2, fallback))

        self.query.tables = old_tables
        return joins, params

    def join_with_locale(self, alias, fallback=None):
        # This is all lifted from the real sql.compiler.get_from_clause(),
        # except for the extra AND clause.  Fun project: fix Django to use Q
        # objects here instead of a bunch of strings.
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        mapping = self.query.alias_map[alias]
        name, alias, join_type, lhs, lhs_col, col, nullable = mapping
        alias_str = (alias != name and ' %s' % alias or '')

        if isinstance(fallback, models.Field):
            fallback_str = '%s.%s' % (qn(self.query.model._meta.db_table),
                                      qn(fallback.column))
        else:
            fallback_str = '%s'

        return ('%s %s%s ON (%s.%s = %s.%s AND %s.%s = %s)' %
                (join_type, qn(name), alias_str,
                 qn(lhs), qn2(lhs_col), qn(alias), qn2(col),
                 qn(alias), qn('locale'), fallback_str))
