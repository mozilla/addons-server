import re
from functools import total_ordering

from django.db import connections, models, router
from django.db.models.deletion import Collector

import markdown as md
from justhtml import (
    Edit,
    JustHTML,
    Linkify,
    SanitizationPolicy,
    Sanitize,
    SetAttrs,
    Unwrap,
    UrlPolicy,
    UrlRule,
)

import olympia.core.logger
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ManagerBase, ModelBase
from olympia.amo.urlresolvers import linkify_bounce_url_callback

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
    """Run the string through JustHTML to get version with escaped HTML."""

    allowed_tags = []
    allowed_attributes = {}

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

        cleaned = self.clean_localized_string()
        self.localized_string_clean = clean_nl(cleaned).strip()

    def clean_localized_string(self):
        fragment = JustHTML(
            str(self.localized_string),
            fragment=True,
            transforms=[Sanitize(policy=self.get_sanitization_policy({}, {'*': []}))],
        )
        return fragment.to_html(pretty=False)

    def get_sanitization_policy(self, tags, attr, tag_handling='escape'):
        return SanitizationPolicy(
            allowed_tags=tags,
            allowed_attributes=attr,
            # Prevent JustHTML from dropping <script> and <style>
            # regardless of disallowed_tag_handling.
            drop_content_tags=(),
            disallowed_tag_handling=tag_handling,
            # Prevent JustHTML from dropping href without an explicit URLPolicy.
            url_policy=UrlPolicy(
                allow_rules={
                    ('a', 'href'): UrlRule(
                        allowed_schemes=['http', 'https'],
                        handling='allow',
                    )
                },
            ),
        )


class PurifiedTranslation(PureTranslation):
    """Run the string through JustHTML to get a safe version."""

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

    linkify_transform = [
        Linkify(),
        Edit('a', linkify_bounce_url_callback),
        SetAttrs('a', rel='nofollow'),
    ]

    class Meta:
        proxy = True

    def __html__(self):
        return str(self)

    def clean_localized_string(self):
        # Keep only the allowed tags and attributes, escape the rest.
        fragment = JustHTML(
            str(self.localized_string),
            fragment=True,
            transforms=[
                Sanitize(
                    policy=self.get_sanitization_policy(
                        self.allowed_tags, self.allowed_attributes
                    )
                )
            ]
            + self.linkify_transform,
        )
        return fragment.to_html(pretty=False)


class PurifiedMarkdownTranslation(PurifiedTranslation):
    class Meta:
        proxy = True

    def clean_localized_string(self):
        cleaned = JustHTML(
            str(self.localized_string) if self.localized_string else '',
            fragment=True,
            transforms=[Sanitize(policy=self.get_sanitization_policy({}, {'*': []}))],
        ).to_html(pretty=False)

        # hack; cleaning breaks blockquotes
        text_with_brs = cleaned.replace('&gt;', '>')

        # the base syntax of markdown library does not provide abbreviations or fenced
        # code. see https://python-markdown.github.io/extensions/
        markdown = md.markdown(text_with_brs, extensions=['abbr', 'fenced_code'])

        # Markdown wraps paragraphs in <p>, which bleach used to unwrap into newlines.
        # justHTML does not, so this needs to be manually accounted for.
        markdown = re.sub(r'(</\w+>)\s*<p[^>]*>', r'\1\n\n', markdown)

        fragment = JustHTML(
            markdown,
            fragment=True,
            transforms=[
                Unwrap('p'),  # Remove the outer <p> wrapper generated by markdown.
                Sanitize(
                    policy=self.get_sanitization_policy(
                        self.allowed_tags, self.allowed_attributes, tag_handling='drop'
                    ),
                ),
            ]
            + self.linkify_transform,
        )

        return fragment.to_html(pretty=False)


class LinkifiedTranslation(PurifiedTranslation):
    """Run the string through JustHTML to get a linkified version."""

    allowed_tags = ['a']

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
