import re

from django.db import models, connection
from django.utils import encoding

import bleach
import html5lib
from html5lib.serializer.htmlserializer import HTMLSerializer

import amo.models
from amo import urlresolvers
from . import utils


class Translation(amo.models.ModelBase):
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

    @property
    def cache_key(self):
        return self._cache_key(self.id)

    @classmethod
    def _cache_key(cls, pk):
        # Hard-coding the class name here so that subclasses don't try to cache
        # themselves under something like "o:translations.purifiedtranslation".
        key_parts = ('o', 'translations.translation', pk)
        return ':'.join(map(encoding.smart_unicode, key_parts))

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
            trans = cls(localized_string=string, **q)

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
        cleaned = bleach.clean(self.localized_string)
        linkified = bleach.linkify(cleaned, nofollow=True,
                filter_url=urlresolvers.get_outgoing_url)
        self.localized_string_clean = self.clean_nl(linkified).strip()

    def clean_nl(self, string):
        """ This will clean up newlines so that nl2br can properly
            be called on the cleaned text. """

        html_blocks = ['blockquote', 'ol', 'li', 'ul']

        if not string:
            return string

        def parse_html(tree):
            prev_tag = ""
            for i, node in enumerate(tree.childNodes):
                if node.type == 4:  # Text node
                    value = node.value

                    # Strip new lines directly inside block level elements.
                    if node.parent.name in html_blocks:
                        value = value.strip('\n')

                    # Remove the first new line after a block level element
                    if (prev_tag in html_blocks and value.startswith('\n')):
                        value = value[1:]

                    tree.childNodes[i].value = value
                else:
                    tree.insertBefore(parse_html(node), node)
                    tree.removeChild(node)

                prev_tag = node.name
            return tree

        parse = parse_html(html5lib.parseFragment(string))

        walker = html5lib.treewalkers.getTreeWalker('simpletree')
        stream = walker(parse)
        serializer = HTMLSerializer(quote_attr_values=True,
                                    omit_optional_tags=False)

        return serializer.render(stream)

    def __truncate__(self, length, killwords, end):
        return utils.truncate(unicode(self), length, killwords, end)


class LinkifiedTranslation(PurifiedTranslation):
    """Run the string through bleach to get a linkified version."""

    class Meta:
        proxy = True

    def clean(self):
        linkified = bleach.linkify(self.localized_string,
                filter_url=urlresolvers.get_outgoing_url)
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
    obj.update(**{field.name: None})
    if trans:
        Translation.objects.filter(id=trans.id).delete()
