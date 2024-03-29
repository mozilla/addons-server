from django.conf import settings
from django.db import connections, models, router
from django.utils import translation

from olympia.translations.models import Translation


isnull = """IF(!ISNULL({t1}.`localized_string`), {t1}.`{col}`, {t2}.`{col}`)
            AS {name}_{col}"""
join = """LEFT OUTER JOIN `translations` {t}
          ON ({t}.`id`={model}.`{name}` AND {t}.`locale`={locale})"""
no_locale_join = """LEFT OUTER JOIN `translations` {t}
                    ON {t}.`id`={model}.`{name}`"""

trans_fields = [f.name for f in Translation._meta.fields]


def _build_query(*, model, connection, fields):
    qn = connection.ops.quote_name
    selects, joins, params = [], [], []

    # The model can define a fallback locale (which may be a Field).
    if hasattr(model, 'get_fallback'):
        fallback = model.get_fallback()
    else:
        fallback = settings.LANGUAGE_CODE

    # Add the selects and joins for each field on the model passed to this function.
    for field in fields:
        if isinstance(fallback, models.Field):
            fallback_str = f'{qn(model._meta.db_table)}.{qn(fallback.column)}'
        else:
            fallback_str = '%s'

        name = field.column
        data = {
            't1': 't1_' + name,
            't2': 't2_' + name,
            'model': qn(model._meta.db_table),
            'name': name,
        }

        selects.extend(isnull.format(col=f, **data) for f in trans_fields)

        joins.append(join.format(t=data['t1'], locale='%s', **data))
        params.append(translation.get_language())

        if field.require_locale:
            joins.append(join.format(t=data['t2'], locale=fallback_str, **data))
            if not isinstance(fallback, models.Field):
                params.append(fallback)
        else:
            joins.append(no_locale_join.format(t=data['t2'], **data))

    # ids will be added later on.
    sql = """SELECT {model}.{pk}, {selects} FROM {model} {joins}
             WHERE {model}.{pk} IN {{ids}}"""
    query = sql.format(
        selects=','.join(selects),
        joins='\n'.join(joins),
        model=qn(model._meta.db_table),
        pk=qn(model._meta.pk.column),
    )
    return query, params


def get_trans(items):
    if not items:
        return

    first_item = items[0]
    model = first_item.__class__
    assert hasattr(model._meta, 'translated_fields')
    deferred_fields = first_item.get_deferred_fields()
    fields = [
        field
        for field in model._meta.translated_fields
        if field.attname not in deferred_fields
    ]
    if not fields:
        return
    # FIXME: if we knew which db the queryset we are transforming used, we
    # could make sure we are re-using the same one.
    dbname = router.db_for_read(model)
    connection = connections[dbname]
    sql, params = _build_query(model=model, connection=connection, fields=fields)
    item_dict = {item.pk: item for item in items}
    ids = ','.join(map(str, item_dict.keys()))

    with connection.cursor() as cursor:
        cursor.execute(sql.format(ids='(%s)' % ids), tuple(params))
        step = len(trans_fields)
        for row in cursor.fetchall():
            # We put the item's pk as the first selected field.
            item = item_dict[row[0]]
            for index, field in enumerate(fields):
                start = 1 + step * index
                t = Translation(*row[start : start + step])
                if t.id is not None and t.localized_string is not None:
                    setattr(item, field.name, t)
