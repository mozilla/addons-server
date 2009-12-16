from django.db import models, connection


class Translation(models.Model):
    """
    Translation model.

    Use :class:`translations.fields.TranslatedField` instead of a plain foreign
    key to this model.
    """

    autoid = models.AutoField(primary_key=True)
    # id is not really unique.  See the story in translations/sql/.
    id = models.IntegerField(unique=True)
    locale = models.CharField(max_length=10)
    localized_string = models.TextField()

    # These are normally from amo.ModelBase, but we don't want to have weird
    # circular dependencies between ModelBase and Translations.
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'translations'
        unique_together = ('id', 'locale')

    def __unicode__(self):
        return self.localized_string

    @classmethod
    def new(cls, string, locale, id=None):
        """
        Jumps through all the right hoops to create a new translation.

        If ``id`` is not given a new id will be created using
        ``translations_seq``.  Otherwise, the id will be used to add strings to
        an existing translation.
        """
        if id is None:
            # Get a sequence key for the new translation.
            cursor = connection.cursor()
            cursor.execute("""UPDATE translations_seq
                              SET id=LAST_INSERT_ID(id + 1)""")
            cursor.execute('SELECT LAST_INSERT_ID() FROM translations_seq')
            id = cursor.fetchone()[0]

        return Translation.objects.create(id=id, localized_string=string,
                                          locale=locale)


class TranslationSequence(models.Model):
    """
    The translations_seq table, so syncdb will create it during testing.
    """
    id = models.IntegerField(primary_key=True)

    class Meta:
        db_table = 'translations_seq'
