from django.conf import settings
from django.db import connections, models, router
from django.utils import translation

from translations.models import Translation
from translations.fields import TranslatedField

isnull = """IF(!ISNULL({t1}.localized_string),
               {t1}.{col},
               IF(!ISNULL({t2}.localized_string),
                  {t2}.{col},
                  IF(!ISNULL(
                     {t3}.localized_string), {t3}.{col}, {t4}.{col})))
            AS {name}_{col}"""
join = """LEFT OUTER JOIN translations {t}
          ON ({t}.id={model}.{name} AND {t}.locale={locale})"""
no_locale_join = """LEFT OUTER JOIN translations {t}
                    ON {t}.id={model}.{name}"""

trans_fields = [f.name for f in Translation._meta.fields]


def build_query(model, connection):
    qn = connection.ops.quote_name
    selects, joins, params = [], [], []

    # We will try to find a translation for locales in the following order:
    # 1. The activate language
    # 2. The fallback locale if provided by the model
    # 3. settings.LANGUAGE_CODE
    # 4. Just any translation
    locales = [translation.get_language()]

    # The model can define a fallback locale (which may be a Field).
    if hasattr(model, 'get_fallback'):
        locales.append(model.get_fallback())
    else:
        locales.append(settings.LANGUAGE_CODE)
    locales.append(settings.LANGUAGE_CODE)

    if not hasattr(model._meta, 'translated_fields'):
        model._meta.translated_fields = [f for f in model._meta.fields
                                         if isinstance(f, TranslatedField)]

    # Add the selects and joins for each translated field on the model.
    for field in model._meta.translated_fields:
        #if isinstance(fallback, models.Field):
        #    fallback_str = '%s.%s' % (qn(model._meta.db_table),
        #                              qn(fallback.column))
        #else:
        #    fallback_str = '%s'

        name = field.column
        d = {'model': qn(model._meta.db_table), 'name': name}
        for i, locale in enumerate(locales, start=1):
            d['t{0}'.format(i)] = 't{0}_{1}'.format(i, name)
            if isinstance(locale, models.Field):
                joins.append(join.format(t=d['t{0}'.format(i)],
                                         locale='{0}.{1}'.format(
                                             qn(model._meta.db_table),
                                             qn(locale.column)),
                                         **d))
            else:
                joins.append(join.format(t=d['t{0}'.format(i)], locale='%s',
                                         **d))
                params.append(locale)
        d['t4'] = 't4_{0}'.format(name)
        joins.append(no_locale_join.format(t=d['t4'], **d))

        selects.extend(isnull.format(col=f, **d) for f in trans_fields)

        #if field.require_locale:
        #    joins.append(join.format(t=d['t2'], locale=fallback_str, **d))
        #    if not isinstance(fallback, models.Field):
        #        params.append(fallback)
        #else:
        #    joins.append(no_locale_join.format(t=d['t2'], **d))

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
