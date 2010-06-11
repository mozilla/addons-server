import itertools

from django.db import models

import amo.models
from translations.fields import TranslatedField, TranslatedFieldMixin
from translations.models import Translation


class Review(TranslatedFieldMixin, amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='_reviews')
    version = models.ForeignKey('versions.Version', related_name='reviews',
                                null=True)
    user = models.ForeignKey('users.UserProfile', related_name='_reviews_all')
    reply_to = models.ForeignKey('self', null=True, unique=True,
                                 db_column='reply_to')

    rating = models.PositiveSmallIntegerField(null=True)
    title = TranslatedField()
    body = TranslatedField()
    ip_address = models.CharField(max_length=255, default='0.0.0.0')

    editorreview = models.BooleanField(default=False)
    flag = models.BooleanField(default=False)
    sandbox = models.BooleanField(default=False)

    # Denormalized fields for easy lookup queries.
    # TODO: index on addon, user, latest
    is_latest = models.BooleanField(default=True, editable=False,
        help_text="Is this the user's latest review for the add-on?")
    previous_count = models.PositiveIntegerField(default=0, editable=False,
        help_text="How many previous reviews by the user for this add-on?")

    class Meta:
        db_table = 'reviews'
        ordering = ('-created',)

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

    @staticmethod
    def post_save(sender, instance, created, **kwargs):
        if created:
            Review.post_delete(sender, instance)

    @staticmethod
    def post_delete(sender, instance, **kwargs):
        from . import tasks
        pair = instance.addon_id, instance.user_id
        tasks.update_denorm(pair)

models.signals.post_save.connect(Review.post_save, sender=Review)
models.signals.post_delete.connect(Review.post_delete, sender=Review)
