from django import forms
from django.conf import settings
from django.forms.util import flatatt
from django.utils import translation
from django.utils.translation.trans_real import to_language

import jinja2

import jingo

from .models import Translation


attrs = 'name="{name}_{locale}" data-locale="{locale}" {attrs}'
input = u'<input %s value="{value}">' % attrs
textarea = u'<textarea %s>{value}</textarea>' % attrs


def get_string(x):
    locale = translation.get_language()
    try:
        return (Translation.objects.filter(id=x, locale=locale)
                .filter(localized_string__isnull=False)
                .values_list('localized_string', flat=True)[0])
    except IndexError:
        return u''


class TranslationTextInput(forms.widgets.TextInput):
    """A simple textfield replacement for collecting translated names."""

    def _format_value(self, value):
        if isinstance(value, long):
            return get_string(value)
        return value


class TranslationTextarea(forms.widgets.Textarea):

    def render(self, name, value, attrs=None):
        if isinstance(value, long):
            value = get_string(value)
        return super(TranslationTextarea, self).render(name, value, attrs)


class TranslationWidget(forms.widgets.Textarea):

    # Django expects ForeignKey widgets to have a choices attribute.
    choices = None

    def render(self, name, value, attrs=None):

        attrs = self.build_attrs(attrs)
        widget = widget_builder(name, attrs)
        id = attrs.pop('id')

        lang = translation.get_language()
        widgets = {}
        widgets[lang] = widget(lang, value='')

        try:
            trans_id = int(value)
            widgets.update(trans_widgets(trans_id, widget))
        except (TypeError, ValueError):
            pass

        languages = dict((i.lower(), j) for i, j in settings.LANGUAGES.items())

        template = jingo.env.get_template('translations/transbox.html')
        return template.render(id=id, name=name, widgets=widgets,
                               languages=languages)

    def value_from_datadict(self, data, files, name):
        # All the translations for this field are called {name}_{locale}, so
        # pull out everything that starts with name.
        rv = {}
        prefix = '%s_' % name
        locale = lambda s: s[len(prefix):]
        delete_locale = lambda s: s[len(prefix):-len('_delete')]
        for key in data:
            if key.startswith(prefix):
                if key.endswith('_delete'):
                    rv[delete_locale(key)] = None
                else:
                    rv[locale(key)] = data[key]
        return rv


def trans_widgets(trans_id, widget):
    translations = (Translation.objects.filter(id=trans_id)
                    .filter(localized_string__isnull=False)
                    .values_list('locale', 'localized_string'))
    return [(to_language(locale), widget(locale, val))
            for locale, val in translations if val is not None]


def widget_builder(name, attrs):

    def widget(locale, value):
        locale = to_language(locale)
        value = jinja2.escape(value)
        attrs_ = dict(id='trans_%s_%s' % (name, locale), **attrs)
        return textarea.format(name=name, locale=locale,
                               attrs=flatatt(attrs_), value=value)
    return widget
