from django.db import models, connection

from bleach import Bleach
import caching.base

from amo import urlresolvers
from . import utils


class MyBleach(Bleach):
    def filter_url(self, url):
        """Pass auto-linked URLs through the redirector."""
        return urlresolvers.get_outgoing_url(url)

bleach = MyBleach()


class Translation(caching.base.CachingMixin, models.Model):
    """
    Translation model.

    Use :class:`translations.fields.TranslatedField` instead of a plain foreign
    key to this model.
    """

    autoid = models.AutoField(primary_key=True)
    id = models.IntegerField()
    locale = models.CharField(max_length=10)
    localized_string = models.TextField(null=True)
    localized_string_clean = models.TextField(null=True)

    # These are normally from amo.models.ModelBase, but we don't want to have
    # weird circular dependencies between ModelBase and Translations.
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'translations'
        unique_together = ('id', 'locale')

    def __unicode__(self):
        return self.localized_string and unicode(self.localized_string) or ''

    def __nonzero__(self):
        # __nonzero__ is called to evaluate an object in a boolean context.  We
        # want Translations to be falsy if their string is empty.
        return (bool(self.localized_string) and
                bool(self.localized_string.strip()))

    def __cmp__(self, other):
        if hasattr(other, 'localized_string'):
            return cmp(self.localized_string, other.localized_string)
        else:
            return cmp(self.localized_string, other)

    def clean(self):
        if self.localized_string:
            self.localized_string = self.localized_string.strip()

    def save(self, **kwargs):
        self.clean()
        return super(Translation, self).save(**kwargs)

    @property
    def cache_key(self):
        return self._cache_key(self.id)

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

            # The sequence table should never be empty. But alas, if it is,
            # let's fix it.
            if not cursor.rowcount > 0:
                cursor.execute("""INSERT INTO translations_seq (id)
                                  VALUES(LAST_INSERT_ID(id + 1))""")

            cursor.execute('SELECT LAST_INSERT_ID() FROM translations_seq')
            id = cursor.fetchone()[0]

        # Update if one exists, otherwise create a new one.
        q = {'id': id, 'locale': locale}
        try:
            trans = cls.objects.get(**q)
            trans.localized_string = string
        except cls.DoesNotExist:
            trans = cls.objects.create(localized_string=string, **q)

        return trans


class PurifiedTranslation(Translation):
    """Run the string through bleach to get a safe, linkified version."""

    class Meta:
        proxy = True

    def __unicode__(self):
        if not self.localized_string_clean:
            self.clean()
        return unicode(self.localized_string_clean)

    def __html__(self):
        return unicode(self)

    def clean(self):
        super(PurifiedTranslation, self).clean()
        self.localized_string_clean = bleach.bleach(self.localized_string)

    def __truncate__(self, length, killwords, end):
        return utils.truncate(unicode(self), length, killwords, end)


class LinkifiedTranslation(PurifiedTranslation):
    """Run the string through bleach to get a linkified version."""

    class Meta:
        proxy = True

    def clean(self):
        linkified = bleach.linkify(self.localized_string)
        clean = bleach.clean(linkified, tags=['a'],
                             attributes={'a': ['href', 'rel']})
        self.localized_string_clean = clean


class TranslationSequence(models.Model):
    """
    The translations_seq table, so syncdb will create it during testing.
    """
    id = models.IntegerField(primary_key=True)

    class Meta:
        db_table = 'translations_seq'


def delete_translation(obj, fieldname):
    field = obj._meta.get_field(fieldname)
    trans = getattr(obj, field.name)
    obj.update(**{field.name:None})
    Translation.objects.filter(id=trans.id).delete()
