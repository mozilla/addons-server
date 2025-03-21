from functools import total_ordering

from django.db import connections, models, router
from django.db.models.deletion import Collector

import markdown as md
import nh3

import olympia.core.logger
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ManagerBase, ModelBase
from olympia.amo.urlresolvers import linkify_and_clean, outgoing_href_attributes_filter

from . import utils


log = olympia.core.logger.getLogger('z.translations')


class TranslationManager(ManagerBase):
    def remove_for(self, obj, locale):
        """Remove a locale for the given object."""
        ids = [getattr(obj, f.attname) for f in obj._meta.translated_fields]
        qs = Translation.objects.filter(id__in=filter(None, ids), locale=locale)
        qs.update(localized_string=None, localized_string_clean=None)


@total_ordering
class Translation(ModelBase):
    """
    Translation model.

    Use :class:`translations.fields.TranslatedField` instead of a plain foreign
    key to this model.
    """

    autoid = PositiveAutoField(primary_key=True)
    id = models.PositiveIntegerField()
    locale = models.CharField(max_length=10)
    localized_string = models.TextField(null=True)
    localized_string_clean = models.TextField(null=True)

    objects = TranslationManager()

    class Meta:
        db_table = 'translations'
        constraints = [
            models.UniqueConstraint(fields=('id', 'locale'), name='id'),
        ]

    def __str__(self):
        return str(self.localized_string) if self.localized_string else ''

    def __repr__(self):
        return f'<{self._meta.object_name}: {self.locale}: {self.__str__()}>'

    def __bool__(self):
        # __bool__ is called to evaluate an object in a boolean context.
        # We want Translations to be falsy if their string is empty.
        return bool(self.localized_string) and bool(self.localized_string.strip())

    def __lt__(self, other):
        if hasattr(other, 'localized_string'):
            return self.localized_string < other.localized_string
        else:
            return self.localized_string < other

    def __eq__(self, other):
        # Django implements an __eq__ that only checks pks. We need to check
        # the strings if we're dealing with existing vs. unsaved Translations.
        if hasattr(other, 'localized_string'):
            return self.localized_string == other.localized_string
        else:
            return self.localized_string == other

    def __hash__(self):
        return hash(self.localized_string)

    def clean(self):
        if self.localized_string:
            self.localized_string = self.localized_string.strip()

    def save(self, **kwargs):
        self.clean()
        return super().save(**kwargs)

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
            return super().delete(using=using)

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
                cursor.execute(
                    """
                    UPDATE `translations_seq`
                    SET `id`=LAST_INSERT_ID(
                        `id` + @@global.auto_increment_increment
                    )
                """
                )

                # The sequence table should never be empty. But alas, if it is,
                # let's fix it.
                if not cursor.rowcount > 0:
                    cursor.execute(
                        """
                        INSERT INTO `translations_seq` (`id`)
                        VALUES(LAST_INSERT_ID(
                            `id` + @@global.auto_increment_increment
                        ))
                    """
                    )
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


class PureTranslation(Translation):
    """Run the string through nh3 to get version with escaped HTML."""

    allowed_tags = set()
    allowed_attributes = {}
    attribute_filter = None
    clean_method = staticmethod(nh3.clean)

    class Meta:
        proxy = True

    def __str__(self):
        if not self.localized_string_clean:
            self.clean()
        return str(self.localized_string_clean)

    def __truncate__(self, length, killwords, end):
        return utils.truncate(str(self), length, killwords, end)

    def clean(self):
        from olympia.amo.utils import clean_nl

        cleaned = self.clean_string(self.localized_string)
        self.localized_string_clean = clean_nl(cleaned).strip()

    def clean_string(self, text):
        return (
            self.clean_method(
                str(text),
                tags=self.allowed_tags,
                attributes=self.allowed_attributes,
                attribute_filter=self.attribute_filter,
            )
            if text
            else ''
        )


class PurifiedTranslation(PureTranslation):
    """Run the string through nh3 to get a safe version."""

    allowed_tags = {
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
    }
    allowed_attributes = {
        'a': {'href', 'title'},
        'abbr': {'title'},
        'acronym': {'title'},
    }
    attribute_filter = outgoing_href_attributes_filter
    clean_method = staticmethod(linkify_and_clean)

    class Meta:
        proxy = True

    def __html__(self):
        return str(self)

    @classmethod
    def get_allowed_tags(cls):
        return ', '.join(cls.allowed_tags)


class PurifiedMarkdownTranslation(PurifiedTranslation):
    class Meta:
        proxy = True

    def clean_string(self, text):
        # bleach user-inputted html first.
        cleaned = (
            nh3.clean(text, tags=set(), attributes={}) if self.localized_string else ''
        )
        # hack; cleaning breaks blockquotes
        text_with_brs = cleaned.replace('&gt;', '>')
        # the base syntax of markdown library does not provide abbreviations or fenced
        # code. see https://python-markdown.github.io/extensions/
        html = md.markdown(text_with_brs, extensions=['abbr', 'fenced_code'])

        # Run through cleaning as normal
        return super().clean_string(html)


class LinkifiedTranslation(PurifiedTranslation):
    """Run the string through bleach to get a linkified version."""

    allowed_tags = {'a'}

    class Meta:
        proxy = True


class NoURLsTranslation(PureTranslation):
    """Strip the string of URLs and escape any HTML."""

    class Meta:
        proxy = True

    def __str__(self):
        # Clean string if that hasn't been done already. Unlike PurifiedTranslation,
        # this class doesn't implement __html__(), because it's designed to contain
        # only text. All raw HTML is escaped.
        if not self.localized_string_clean and self.localized_string:
            self.clean()
        return str(self.localized_string_clean)

    def clean(self):
        from olympia.amo.utils import URL_RE

        super().clean()
        self.localized_string_clean = (
            URL_RE.sub('', self.localized_string_clean).strip()
            if self.localized_string_clean
            else self.localized_string_clean
        )


class TranslationSequence(models.Model):
    """
    The translations_seq table, so migrations will create it during testing.
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
