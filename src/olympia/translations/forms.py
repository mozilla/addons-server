from django.forms import ValidationError
from django.conf import settings
from django.db import models
from django.forms.utils import ErrorList
from django.utils.translation.trans_real import to_language
from django.utils.encoding import force_text
from django.utils.html import format_html, format_html_join, conditional_escape


def default_locale(obj):
    """Get obj's default locale."""
    if hasattr(obj, 'get_fallback'):
        fallback = obj.get_fallback()
        if isinstance(fallback, models.Field):
            fallback = getattr(obj, fallback.name)
        return fallback
    else:
        return settings.LANGUAGE_CODE


class TranslationFormMixin(object):
    """
    A mixin for forms with translations that tells fields about the object's
    default locale.
    """

    def __init__(self, *args, **kw):
        super(TranslationFormMixin, self).__init__(*args, **kw)
        self.error_class = LocaleErrorList
        self.set_default_locale()

    def set_default_locale(self):
        locale = to_language(default_locale(self.instance))
        for field in self.fields.values():
            field.default_locale = locale
            field.widget.default_locale = locale

    def full_clean(self):
        self.set_default_locale()
        return super(TranslationFormMixin, self).full_clean()


class LocaleErrorList(ErrorList):

    def _errors(self):
        # Pull error messages out of (locale, error) pairs.
        return (e[1] if isinstance(e, tuple) else e
                for e in self)

    def __contains__(self, value):
        return value in self._errors()

    def as_ul(self):
        if not self.data:
            return u''

        li = []
        for item in self:
            if isinstance(item, tuple):
                locale, e = item
                extra = ' data-lang="%s"' % locale
            else:
                e, extra = item, ''
            li.append((extra, conditional_escape(force_text(e))))

        return format_html(
            '<ul class="{}">{}</ul>',
            self.error_class,
            format_html_join(
                '',
                '<li{}>{}</li>',
                ((force_text(extra), force_text(elem)) for extra, elem in li)
            )
        )

    # Override Django 1.7's `__getitem__` which wraps the error with
    # `force_text` converting our tuples to strings.
    def __getitem__(self, i):
        error = self.data[i]
        if isinstance(error, ValidationError):
            return list(error)[0]
        elif isinstance(error, tuple):
            return error
        else:
            return force_text(error)
