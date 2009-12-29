from django.conf import settings
from django.db import models

import amo
from translations.fields import TranslatedField, translations_with_fallback


class Addon(amo.ModelBase):
    name = TranslatedField()
    description = TranslatedField()

    adminreview = models.BooleanField(default=False)
    defaultlocale = models.CharField(max_length=10,
                                     default=settings.LANGUAGE_CODE)

    users = models.ManyToManyField('users.User')

    class Meta:
        db_table = 'addons'

    def get_absolute_url(self):
        # XXX: use reverse
        return '/addon/%s' % self.id

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.defaultlocale)
