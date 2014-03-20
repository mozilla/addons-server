from django.conf import settings
from django.db import connections, models, router
from django.utils import translation

from translations.models import Translation
from translations.fields import TranslatedField

isnull_tpl = """IF(!ISNULL({alias}.localized_string),
                        {alias}.{col},
                        {else_})"""
join_tpl = """LEFT OUTER JOIN translations {alias}
                        ON ({alias}.id={model}.{name} AND
                            {alias}.locale={locale})"""
no_locale_join_tpl = """LEFT OUTER JOIN translations {alias}
                                  ON {alias}.id={model}.{name}"""

trans_fields = [f.name for f in Translation._meta.fields]


def build_query(model, connection):
    """Build the query to retrieve translations for a given model.

    We will try to find a translation for locales in the following order:
    1. The active language
    2. The fallback locale if provided by the model via get_fallback()
    3. settings.LANGUAGE_CODE
    If none of those were found, return just any translation.

    Only try a locale if it hasn't been tried before, to optimize the number of
    joins.

    Eg, if the active language is 'en-US' and there's no fallback locale for
    the model (no ``get_fallback()`` method), then we're only doing two joins:
    one for 'en-US' (active language and settings.LANGUAGE_CODE), and one for
    the "last chance fallback" (which returns just any translation).

    """
    qn = connection.ops.quote_name
    selects, joins, params = [], [], []

    # Populate the model._meta.translated_fields if needed.
    if not hasattr(model._meta, 'translated_fields'):
        model._meta.translated_fields = [f for f in model._meta.fields
                                         if isinstance(f, TranslatedField)]

    locales = [translation.get_language()]  # First choice.

    # Second choice: the model can define a fallback (which may be a Field).
    fallback_field = None
    if hasattr(model, 'get_fallback'):
        fallback = model.get_fallback()
        if isinstance(fallback, models.Field):
            # If it's a field, match on the column directly. We can't be sure
            # that the fallback field is loaded (eg if ".only()" was used), so
            # it's not possible to avoid a join here, even if the fallback
            # locale is already tested.
            fallback_field = '{0}.{1}'.format(qn(model._meta.db_table),
                                              qn(fallback.column))
            locales.append(fallback_field)
        elif fallback not in locales:
            locales.append(fallback)

    # Third choice.
    if settings.LANGUAGE_CODE not in locales:
        locales.append(settings.LANGUAGE_CODE)

    # Add the selects and joins for each translated field on the model.
    for field in model._meta.translated_fields:
        name = field.column
        d = {'model': qn(model._meta.db_table), 'name': name}

        # Add the selects and joins for each locale to try, for this field.
        isnull = isnull_tpl
        for i, locale in enumerate(locales, start=0):
            alias = 't{0}_{1}'.format(i, name)  # DB alias for the join.
            # Inception: we need the "else" clause to be another "isnull"
            # element. We replace {col} with itself, as we're not ready to fill
            # that in yet, it'll be done when building the ``selects`` below.
            isnull = isnull.format(alias=alias, else_=isnull_tpl, col='{col}')

            if locale == fallback_field:
                locale_str = fallback_field
            else:
                locale_str = '%s'
                params.append(locale)
            joins.append(join_tpl.format(alias=alias, locale=locale_str, **d))

        # We now add the last fallback: return just any translation.
        alias = 't{0}_{1}'.format(i + 1, name)
        # End of the "inception" here for the else clause.
        else_ = '{alias}.{col}'.format(alias=alias, col='{col}')
        isnull = isnull.format(alias=alias, else_=else_, col='{col}')
        joins.append(no_locale_join_tpl.format(alias=alias, **d))

        selects.extend(isnull.format(col=f) for f in trans_fields)

    # ids will be added later on.
    sql = """SELECT {model}.{pk}, {selects} FROM {model} {joins}
             WHERE {model}.{pk} IN {{ids}}"""
    s = sql.format(selects=','.join(selects), joins='\n'.join(joins),
                   model=qn(model._meta.db_table), pk=model._meta.pk.column)
    return s, params


def get_trans(items):
    if not items:
        return

    model = items[0].__class__
    # FIXME: if we knew which db the queryset we are transforming used, we could
    # make sure we are re-using the same one.
    dbname = router.db_for_read(model)
    connection = connections[dbname]
    sql, params = build_query(model, connection)
    item_dict = dict((item.pk, item) for item in items)
    ids = ','.join(map(str, item_dict.keys()))

    cursor = connection.cursor()
    cursor.execute(sql.format(ids='(%s)' % ids), tuple(params))
    step = len(trans_fields)
    for row in cursor.fetchall():
        # We put the item's pk as the first selected field.
        item = item_dict[row[0]]
        for index, field in enumerate(model._meta.translated_fields):
            start = 1 + step * index
            t = Translation(*row[start:start+step])
            if t.id is not None and t.localized_string is not None:
                setattr(item, field.name, t)
