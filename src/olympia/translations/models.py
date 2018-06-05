from django.db import connections, models, router
from django.db.models.deletion import Collector
from django.utils.encoding import force_text

import bleach

import olympia.core.logger

from olympia.amo import urlresolvers
from olympia.amo.models import ManagerBase, ModelBase

from . import utils


log = olympia.core.logger.getLogger('z.translations')


class TranslationManager(ManagerBase):

    def remove_for(self, obj, locale):
        """Remove a locale for the given object."""
        ids = [getattr(obj, f.attname) for f in obj._meta.translated_fields]
        qs = Translation.objects.filter(id__in=filter(None, ids),
                                        locale=locale)
        qs.update(localized_string=None, localized_string_clean=None)


class Translation(ModelBase):
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

    objects = TranslationManager()

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

    def __eq__(self, other):
        # Django implements an __eq__ that only checks pks.  We need to check
        # the strings if we're dealing with existing vs. unsaved Translations.
        return self.__cmp__(other) == 0

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

    def delete(self, using=None):
        # FIXME: if the Translation is the one used as default/fallback,
        # then deleting it will mean the corresponding field on the related
        # model will stay empty even if there are translations in other
        # languages!
        cls = self.__class__
        using = using or router.db_for_write(cls, instance=self)
        # Look for all translations for the same string (id=self.id) except the
        # current one (autoid=self.autoid).
        qs = cls.objects.filter(id=self.id).exclude(autoid=self.autoid)
        if qs.using(using).exists():
            # If other Translations for the same id exist, we just need to
            # delete this one and *only* this one, without letting Django
            # collect dependencies (it'd remove the others, which we want to
            # keep).
            assert self._get_pk_val() is not None
            collector = Collector(using=using)
            collector.collect([self], collect_related=False)
            # In addition, because we have FK pointing to a non-unique column,
            # we need to force MySQL to ignore constraints because it's dumb
            # and would otherwise complain even if there are remaining rows
            # that matches the FK.
            with connections[using].constraint_checks_disabled():
                collector.delete()
        else:
            # If no other Translations with that id exist, then we should let
            # django behave normally. It should find the related model and set
            # the FKs to NULL.
            return super(Translation, self).delete(using=using)

    delete.alters_data = True

    @classmethod
    def new(cls, string, locale, id=None):
        """
        Jumps through all the right hoops to create a new translation.

        If ``id`` is not given a new id will be created using
        ``translations_seq``.  Otherwise, the id will be used to add strings to
        an existing translation.

        To increment IDs we use a setting on MySQL. This is to support multiple
        database masters -- it's just crazy enough to work! See bug 756242.
        """
        if id is None:
            # Get a sequence key for the new translation.
            with connections['default'].cursor() as cursor:
                cursor.execute("""
                    UPDATE translations_seq
                    SET id=LAST_INSERT_ID(
                        id + @@global.auto_increment_increment
                    )
                """)

                # The sequence table should never be empty. But alas, if it is,
                # let's fix it.
                if not cursor.rowcount > 0:
                    cursor.execute("""
                        INSERT INTO translations_seq (id)
                        VALUES(LAST_INSERT_ID(
                            id + @@global.auto_increment_increment
                        ))
                    """)
                cursor.execute('SELECT LAST_INSERT_ID()')
                id = cursor.fetchone()[0]

        # Update if one exists, otherwise create a new one.
        q = {'id': id, 'locale': locale}
        try:
            trans = cls.objects.get(**q)
            trans.localized_string = string
        except cls.DoesNotExist:
            trans = cls(localized_string=string, **q)

        return trans


class PurifiedTranslation(Translation):
    """Run the string through bleach to get a safe version."""
    allowed_tags = [
        'a',
        'abbr',
        'acronym',
        'b',
        'blockquote',
        'code',
        'em',
        'i',
        'li',
        'ol',
        'strong',
        'ul',
    ]
    allowed_attributes = {
        'a': ['href', 'title', 'rel'],
        'abbr': ['title'],
        'acronym': ['title'],
    }

    class Meta:
        proxy = True

    def __unicode__(self):
        if not self.localized_string_clean:
            self.clean()
        return unicode(self.localized_string_clean)

    def __html__(self):
        return unicode(self)

    def __truncate__(self, length, killwords, end):
        return utils.truncate(unicode(self), length, killwords, end)

    def clean(self):
        from olympia.amo.utils import clean_nl
        super(PurifiedTranslation, self).clean()
        cleaned = self.clean_localized_string()
        self.localized_string_clean = clean_nl(cleaned).strip()

    def clean_localized_string(self):
        # All links (text and markup) are normalized.
        linkified = urlresolvers.linkify_with_outgoing(self.localized_string)
        # Keep only the allowed tags and attributes, escape the rest.
        return bleach.clean(linkified, tags=self.allowed_tags,
                            attributes=self.allowed_attributes)


class LinkifiedTranslation(PurifiedTranslation):
    """Run the string through bleach to get a linkified version."""
    allowed_tags = ['a']

    class Meta:
        proxy = True


class NoLinksMixin(object):
    """Mixin used to remove links (URLs and text) from localized_string."""

    def clean_localized_string(self):
        # First pass: bleach everything, but leave links untouched.
        cleaned = super(NoLinksMixin, self).clean_localized_string()

        # Second pass: call linkify to empty the inner text of all links.
        emptied_links = bleach.linkify(
            cleaned, callbacks=[lambda attrs, new: {'_text': ''}])

        # Third pass: now strip links (only links will be stripped, other
        # forbidden tags are already bleached/escaped.
        allowed_tags = self.allowed_tags[:]  # Make a copy.
        allowed_tags.remove('a')
        return bleach.clean(emptied_links, tags=allowed_tags, strip=True)


class NoLinksTranslation(NoLinksMixin, PurifiedTranslation):
    """Run the string through bleach, escape markup and strip all the links."""

    class Meta:
        proxy = True


class NoLinksNoMarkupTranslation(NoLinksMixin, LinkifiedTranslation):
    """Run the string through bleach, escape markup and strip all the links."""

    class Meta:
        proxy = True


class TranslationSequence(models.Model):
    """
    The translations_seq table, so syncdb will create it during testing.
    """
    id = models.IntegerField(primary_key=True)

    class Meta:
        db_table = 'translations_seq'


def delete_translation(obj, fieldname):
    field = obj._meta.get_field(fieldname)
    trans_id = getattr(obj, field.attname)
    obj.update(**{field.name: None})
    if trans_id:
        Translation.objects.filter(id=trans_id).delete()
