import itertools

from django.conf import settings
from django.db import models

from django.utils import translation as translation_utils

import addons.query


def order_by_translation(qs, fieldname):
    """
    Order the QuerySet by the translated field, honoring the current and
    fallback locales.  Returns a new QuerySet.

    The model being sorted needs a get_fallback() classmethod that describes
    the fallback locale.  get_fallback() can return a string or a Field.

    We will try to find a translation for locales in the following order:
    1. The active language
    2. The fallback locale if provided by the model via get_fallback()
    3. settings.LANGUAGE_CODE
    If none of those were found, return just any translation.

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

    # Force four LEFT JOINs against the translation table.  We'll hook up the
    # language fallbacks later.
    qs.query = qs.query.clone(TranslationQuery)
    # First: active language.
    t1 = qs.query.join(connection, always_create=True, promote=True)
    # Second: the fallback provided by the model
    t2 = qs.query.join(connection, always_create=True, promote=True)
    # Third: settings.LANGUAGE_CODE
    t3 = qs.query.join(connection, always_create=True, promote=True)
    # Finally, just any translation.
    t4 = qs.query.join(connection, always_create=True, promote=True)
    qs.query.translation_aliases = {field: (t1, t2, t3, t4)}

    f1, f2 = '%s.`localized_string`' % t1, '%s.`localized_string`' % t2
    f3, f4 = '%s.`localized_string`' % t3, '%s.`localized_string`' % t4
    name = 'translated_%s' % field.column
    ifnull = 'IFNULL(%s, IFNULL(%s, IFNULL(%s, %s)))' % (f1, f2, f3, f4)
    prefix = '-' if desc else ''
    return qs.extra(select={name: ifnull},
                    where=['(%s IS NOT NULL OR %s IS NOT NULL OR '
                           ' %s IS NOT NULL OR %s IS NOT NULL)' % (
                               f1, f2, f3, f4)],
                    order_by=[prefix + name]).distinct()


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

        # First: the active language.
        params.append(translation_utils.get_language())
        # Second: fallback could be a string locale or a model field.
        if hasattr(self.query.model, 'get_fallback'):
            fallback = self.query.model.get_fallback()
        else:
            fallback = settings.LANGUAGE_CODE
        if not isinstance(fallback, models.Field):
            params.append(fallback)
        # Third: settings.LANGUAGE_CODE
        params.append(settings.LANGUAGE_CODE)

        # Add our locale-aware joins.  We're not respecting the table ordering
        # Django had in query.tables, but that seems to be ok.
        for field, aliases in self.query.translation_aliases.items():
            t1, t2, t3, t4 = aliases
            joins.append(self.join_with_locale(t1))
            joins.append(self.join_with_locale(t2, fallback))
            joins.append(self.join_with_locale(t3, settings.LANGUAGE_CODE))
            joins.append(self.join_with_locale(t4, 'any'))

        self.query.tables = old_tables
        return joins, params

    def join_with_locale(self, alias, fallback=None):
        """If ``fallback`` is 'any', don't "AND" on the locale at all.

        Not "ANDing" on the locale will get just any translation available, as
        a "last chance" fallback.

        """
        # This is all lifted from the real sql.compiler.get_from_clause(),
        # except for the extra AND clause.  Fun project: fix Django to use Q
        # objects here instead of a bunch of strings.
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        mapping = self.query.alias_map[alias]
        name, alias, join_type, lhs, lhs_col, col, nullable = mapping
        alias_str = (alias != name and ' %s' % alias or '')

        # Compute the "AND" clause (unless we want "any").
        and_ = ''
        if isinstance(fallback, models.Field):
            fallback_str = '%s.%s' % (qn(self.query.model._meta.db_table),
                                      qn(fallback.column))
        else:
            fallback_str = '%s'

        if str(fallback) != 'any':  # if "any": no "AND", return any locale.
            and_ = 'AND %s.%s = %s' % (qn(alias), qn('locale'), fallback_str)

        return ('%s %s%s ON (%s.%s = %s.%s %s)' %
                (join_type, qn(name), alias_str,
                 qn(lhs), qn2(lhs_col), qn(alias), qn2(col),
                 and_))
