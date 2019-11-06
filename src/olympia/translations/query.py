import itertools
from collections import OrderedDict

from django.conf import settings
from django.db import models
from django.db.models.sql import compiler
from django.db.models.sql.constants import LOUTER
from django.db.models.sql.datastructures import Join
from django.utils import translation as translation_utils


def order_by_translation(qs, fieldname, model=None):
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
    model = model or qs.model
    field = model._meta.get_field(fieldname)

    # Doing the manual joins is flying under Django's radar, so we need to make
    # sure the initial alias (the main table) is set up.
    if not qs.query.table_map:
        qs.query.get_initial_alias()

    # Force two new joins against the translation table, without reusing any
    # aliases. We'll hook up the language fallbacks later.
    # Passing `reuse=set()` force new joins, and passing `nullable=True`
    # forces django to make LEFT OUTER JOINs (otherwise django, because we are
    # building the query manually, does not detect that an inner join would
    # remove results and happily simplifies the LEFT OUTER JOINs to
    # INNER JOINs)
    qs.query = qs.query.clone()
    qs.query.__class__ = TranslationQuery
    qs.query.fallback_model = model
    t1 = qs.query.join(
        Join(
            field.remote_field.model._meta.db_table,
            model._meta.db_table,
            None,
            LOUTER,
            field,
            True,
        ),
        reuse=set(),
    )
    t2 = qs.query.join(
        Join(
            field.remote_field.model._meta.db_table,
            model._meta.db_table,
            None,
            LOUTER,
            field,
            True,
        ),
        reuse=set(),
    )

    qs.query.translation_aliases = {field: (t1, t2)}

    f1, f2 = '%s.`localized_string`' % t1, '%s.`localized_string`' % t2
    name = 'translated_%s' % field.column
    ifnull = 'IFNULL(%s, %s)' % (f1, f2)
    prefix = '-' if desc else ''
    return qs.extra(
        select={name: ifnull},
        where=['(%s IS NOT NULL OR %s IS NOT NULL)' % (f1, f2)],
        order_by=[prefix + name],
    )


class TranslationQuery(models.sql.query.Query):
    """
    Overrides sql.Query to hit our special compiler that knows how to JOIN
    translations.
    """

    def clone(self):
        # Maintain translation_aliases across clones.
        c = super(TranslationQuery, self).clone()
        c.translation_aliases = self.translation_aliases
        return c

    def get_compiler(self, using=None, connection=None):
        # Call super to figure out using and connection.
        c = super(TranslationQuery, self).get_compiler(using, connection)
        return SQLCompiler(self, c.connection, c.using)


class SQLCompiler(compiler.SQLCompiler):
    """Overrides get_from_clause to LEFT JOIN translations with a locale."""

    def get_from_clause(self):
        # Temporarily remove translation tables from query.tables so Django
        # doesn't create joins against them.
        # self.query.tables was removed in django2.0+
        old_tables = list(self.query.tables) if hasattr(self.query, 'tables') else None
        old_map = OrderedDict(self.query.alias_map)
        for table in itertools.chain(*self.query.translation_aliases.values()):
            if table in self.query.alias_map:
                if old_tables:
                    self.query.tables.remove(table)
                del self.query.alias_map[table]

        joins, params = super(SQLCompiler, self).get_from_clause()

        # fallback could be a string locale or a model field.
        params.append(translation_utils.get_language())
        model = getattr(self.query, 'fallback_model', self.query.model)
        if hasattr(model, 'get_fallback'):
            fallback = model.get_fallback()
        else:
            fallback = settings.LANGUAGE_CODE
        if not isinstance(fallback, models.Field):
            params.append(fallback)

        # Add our locale-aware joins.  We're not respecting the table ordering
        # Django had in query.tables, but that seems to be ok.
        for field, aliases in self.query.translation_aliases.items():
            t1, t2 = aliases
            joins.append(self.join_with_locale(t1, None, old_map, model))
            joins.append(self.join_with_locale(t2, fallback, old_map, model))

        if old_tables:
            self.query.tables = old_tables
        self.query.alias_map = old_map
        return joins, params

    def join_with_locale(self, alias, fallback, alias_map, model):
        # This is all lifted from the real sql.compiler.get_from_clause(),
        # except for the extra AND clause.  Fun project: fix Django to use Q
        # objects here instead of a bunch of strings.
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name

        join = alias_map[alias]
        lhs_col, rhs_col = join.join_cols[0]
        alias_str = (
            '' if join.table_alias == join.table_name else ' %s' % join.table_alias
        )

        if isinstance(fallback, models.Field):
            fallback_str = '%s.%s' % (qn(model._meta.db_table), qn(fallback.column))
        else:
            fallback_str = '%s'

        return '%s %s%s ON (%s.%s = %s.%s AND %s.%s = %s)' % (
            join.join_type,
            qn(join.table_name),
            alias_str,
            qn(join.parent_alias),
            qn2(lhs_col),
            qn(join.table_alias),
            qn2(rhs_col),
            qn(join.table_alias),
            qn('locale'),
            fallback_str,
        )
