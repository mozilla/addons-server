import itertools

from django.conf import settings
from django.db import models

from django.utils import translation

import addons.query


def get_locales(model, qn):
    """Return the list of locale "strings" (to be used in an SQL) and the
    params to provide for them.

    ``qn`` is the "quote_name" you usually get using
    ``connection.ops.quote_name``, and is used in the case the
    ``get_fallback()`` method on the model returns a field. Its name will be
    quoted to be inserted in the SQL generated.

    Eg: ['%s', '`addons`.`default_fallback`', '%s'], ['fr', 'en-US']

    It only adds a locale if it isn't present already, to avoid useless
    lookups and joins.

    """
    # Get the locales in order.
    # First choice.
    locale_strings = ['%s']
    params = [translation.get_language().lower()]

    # Second choice: the model can define a fallback (which may be a Field).
    if hasattr(model, 'get_fallback'):
        fallback = model.get_fallback()
        if isinstance(fallback, models.Field):
            # If it's a field, match on the column directly. We can't be sure
            # that the fallback field is loaded (eg if ".only()" was used), so
            # it's not possible to avoid a join here, even if the fallback
            # locale is already tested.
            locale_strings.append('{0}.{1}'.format(qn(model._meta.db_table),
                                                   qn(fallback.column)))
        elif fallback not in params:
            locale_strings.append('%s')
            params.append(fallback)

    # Third choice.
    if settings.LANGUAGE_CODE.lower() not in params:
        locale_strings.append('%s')
        params.append(settings.LANGUAGE_CODE.lower())

    return locale_strings, params


def order_by_translation(qs, fieldname):
    """
    Order the QuerySet by the translated field, honoring the current and
    fallback locales. Returns a new QuerySet.

    The model being sorted needs a get_fallback() classmethod that describes
    the fallback locale. get_fallback() can return a string or a Field.

    We try to find a translation for locales in the following order:
    1. The active language
    2. The fallback locale if provided by the model via get_fallback()
    3. settings.LANGUAGE_CODE
    If none of those are found, return just any translation regardless of its
    locale.

    Only try a locale if it hasn't been tried before, to optimize the number of
    joins.

    Eg, if the active language is 'en-US' and there's no fallback locale for
    the model (no ``get_fallback()`` method), then we're only doing two joins:
    one for 'en-US' (active language and settings.LANGUAGE_CODE), and one for
    the "last chance fallback" (which returns just any translation).

    This code is a bit like the one in translations.transformer.build_query,
    but uses a different API.

    Fun(?) project: see if it's possible to factorize the code, and/or use the
    same API for both.

    """
    if fieldname.startswith('-'):
        prefix = '-'
        fieldname = fieldname[1:]
    else:
        prefix = ''

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

    # We only need the number of locales, so fake the "quote_name" function.
    locale_strings, _params = get_locales(model, lambda name: name)

    # Force the LEFT JOINs against the translation table for each locale we
    # want to try. We'll hook up the locales later.
    fields = []
    ifnull = ifnull_tpl = 'IFNULL({field}.`localized_string`, {else_})'
    for locale in locale_strings:
        field_str = qs.query.join(connection, always_create=True, promote=True)
        fields.append(field_str)

        # Compute the "SELECT" clause, eg: "IFNULL(%s, IFNULL(%s, IFNULL(...".
        # Inception: we need the "else" clause to be another "IFNULL" element.
        ifnull = ifnull.format(field=field_str, else_=ifnull_tpl)

    # Add the last fallback: return any translation regardless of its locale.
    field_str = qs.query.join(connection, always_create=True, promote=True)
    fields.append(field_str)
    # End of the "inception" here for the "else" clause of the "IFNULL".
    ifnull = ifnull.format(field=field_str,
                           else_=field_str + '.`localized_string`')

    # Compute the "WHERE" clause, eg: "%s IS NOT NULL OR %s IS NOT NULL OR...".
    not_null = '{0}.`localized_string` IS NOT NULL'
    where_ = ' OR '.join(not_null.format(field) for field in fields)

    name = 'translated_%s' % field.column

    qs.query = qs.query.clone(TranslationQuery)
    qs.query.translation_aliases = {field: fields}
    qs.query.group_by = [name]
    return qs.extra(select={name: ifnull},
                    where=['({0})'.format(where_)],
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

        # Get the locales to try.
        locale_strings, locale_params = get_locales(
            self.query.model, self.quote_name_unless_alias)
        # Add a "None" to the locale_strings: this "no locale" is the last
        # chance fallback which returns just any translation regardless of its
        # locale.
        locale_strings.append(None)

        params.extend(locale_params)

        # Add the joins.  We're not respecting the table ordering Django had in
        # query.tables, but that seems to be ok.
        for _field, aliases in self.query.translation_aliases.items():
            # For each alias, add a join on the locale we want to try.
            # For the last alias, provide a "ON" clause without an "AND" for
            # the last chance fallback which returns just any translation
            # regardless of its locale.
            for alias, locale in zip(aliases, locale_strings):
                joins.append(self.join_with_locale(alias, locale))

        self.query.tables = old_tables
        return joins, params

    def join_with_locale(self, alias, and_locale=None):
        """If ``and_locale`` is None, don't "AND" on the locale at all.

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

        # Compute the "AND" clause.
        and_ = ''
        if and_locale:
            and_ = 'AND %s.%s = %s' % (qn(alias), qn('locale'), and_locale)

        return ('%s %s%s ON (%s.%s = %s.%s %s)' %
                (join_type, qn(name), alias_str,
                 qn(lhs), qn2(lhs_col), qn(alias), qn2(col),
                 and_))
