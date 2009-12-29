import itertools

from django.db import models

import amo
from translations.fields import TranslatedField
from translations.models import Translation
from users.models import User


class Review(amo.ModelBase):

    rating = models.IntegerField(null=True)
    title = TranslatedField()
    body = TranslatedField()

    version = models.ForeignKey('versions.Version')
    user = models.ForeignKey(User)
    reply_to = models.ForeignKey('self', db_column='reply_to', null=True)

    class Meta:
        db_table = 'reviews'

    def fetch_translations(self, ids, lang):
        if not ids:
            return []

        rv = {}
        ts = Translation.objects.filter(id__in=ids)

        # If a translation exists for the current language, use it.  Otherwise,
        # make do with whatever is available.  (Reviewers only write reviews in
        # their language).
        for id, translations in itertools.groupby(ts, lambda t: t.id):
            locales = dict((t.locale, t) for t in translations)
            if lang in locales:
                rv[id] = locales[lang]
            else:
                rv[id] = locales.itervalues().next()

        return rv.values()
