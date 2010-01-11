import itertools

from django.db import models

import amo
from translations.fields import TranslatedField
from translations.models import Translation


class Review(amo.ModelBase):

    version = models.ForeignKey('versions.Version')
    user = models.ForeignKey('users.UserProfile')
    reply_to = models.ForeignKey('self', null=True, unique=True,
                                 db_column='reply_to')

    rating = models.PositiveSmallIntegerField(null=True)
    title = TranslatedField()
    body = TranslatedField()

    editorreview = models.BooleanField(default=False)
    flag = models.BooleanField(default=False)
    sandbox = models.BooleanField(default=False)

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
