from django.conf import settings
from django.db import models
from django.forms import ValidationError
from django.forms.utils import ErrorList
from django.utils.encoding import force_text
from django.utils.html import conditional_escape, format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation.trans_real import to_language

from .fields import LocaleErrorMessage, _TransField


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
    # Hack to restore behavior from pre Django 1.10 times.
    # Django 1.10 enabled `required` rendering for required widgets. That
    # wasn't the case before, this should be fixed properly but simplifies
    # the actual Django 1.11 deployment for now.
    # See https://github.com/mozilla/addons-server/issues/8912 for proper fix.
    use_required_attribute = False

    def __init__(self, *args, **kwargs):
        kwargs['error_class'] = LocaleErrorList
        super(TranslationFormMixin, self).__init__(*args, **kwargs)
        self.set_locale_field_defaults()

    def set_locale_field_defaults(self):
        locale = to_language(default_locale(self.instance))
        for field_name, field in self.fields.items():
            if isinstance(field, _TransField):
                field.set_default_values(
                    field_name=field_name,
                    parent_form=self,
                    default_locale=locale)

    def add_error(self, field, error):
        if isinstance(error, LocaleErrorMessage):
            self._errors.setdefault(field, self.error_class())
            self._errors[field].append(error)

            if field in self.cleaned_data:
                del self.cleaned_data[field]
        else:
            # Didn't come from a translation field, forward
            # to original implementation.
            super(TranslationFormMixin, self).add_error(field, error)

    def full_clean(self):
        self.set_locale_field_defaults()
        return super(TranslationFormMixin, self).full_clean()


class LocaleErrorList(ErrorList):
    def as_ul(self):
        if not self.data:
            return u''

        li = []
        for item in self.data:
            if isinstance(item, LocaleErrorMessage):
                locale, message = item.locale, item.message
                extra = mark_safe(
                    u' data-lang="%s"' % conditional_escape(locale))
            else:
                message, extra = u''.join(list(item)), u''
            li.append((extra, conditional_escape(force_text(message))))

        return mark_safe(format_html(
            u'<ul class="{}">{}</ul>',
            self.error_class,
            format_html_join(
                u'',
                u'<li{}>{}</li>',
                ((extra, elem) for extra, elem in li)
            )
        ))

    def __getitem__(self, i):
        error = self.data[i]
        if isinstance(error, LocaleErrorMessage):
            return error.message
        if isinstance(error, ValidationError):
            return list(error)[0]
        return force_text(error)
