from operator import attrgetter

from django.conf import settings

import amo


def extract(collection):
    attrs = ('id', 'created', 'modified', 'slug', 'author_username',
             'subscribers', 'weekly_subscribers', 'monthly_subscribers',
             'rating', 'listed', 'type', 'application_id')
    d = dict(zip(attrs, attrgetter(*attrs)(collection)))
    d['app'] = d.pop('application_id')
    d['name_sort'] = unicode(collection.name).lower()
    translations = collection.translations
    d['name'] = list(set(string for _, string
                         in translations[collection.name_id]))
    d['description'] = list(set(string for _, string
                                in translations[collection.description_id]))

    # Boost by the number of subscribers.
    d['boost'] = collection.subscribers ** .2

    # Double the boost if the collection is public.
    if collection.listed:
        d['boost'] = max(d['boost'], 1) * 4

    # Indices for each language. languages is a list of locales we want to
    # index with analyzer if the string's locale matches.
    for analyzer, languages in amo.SEARCH_ANALYZER_MAP.iteritems():
        if (not settings.ES_USE_PLUGINS and
            analyzer in amo.SEARCH_ANALYZER_PLUGINS):
            continue

        d['name_' + analyzer] = list(
            set(string for locale, string in translations[collection.name_id]
                if locale.lower() in languages))
        d['description_' + analyzer] = list(
            set(string for locale, string
                in translations[collection.description_id]
                if locale.lower() in languages))

    return d
