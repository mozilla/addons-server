from django import forms
from django.utils import translation
from django.utils.encoding import force_text
from django.utils.safestring import mark_safe
from django.utils.translation.trans_real import to_language

from .models import Translation


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

    def has_changed(self, initial, data):
        return not ((initial is None and data is None) or
                    (force_text(initial) == force_text(data)))


class TransMulti(forms.widgets.MultiWidget):
    """
    Builds the inputs for a translatable field.

    The backend dumps all the available translations into a set of widgets
    wrapped in div.trans and javascript handles the rest of the UI.
    """
    # TODO: Port to proper templates
    choices = None  # Django expects widgets to have a choices attribute.

    def __init__(self, attrs=None):
        # We set up the widgets in render since every Translation needs a
        # different number of widgets.
        super(TransMulti, self).__init__(widgets=[], attrs=attrs)

    def render(self, name, value, attrs=None):
        self.name = name
        value = self.decompress(value)
        if value:
            self.widgets = [self.widget() for _ in value]
        else:
            # Give an empty widget in the default locale.
            default_locale = getattr(self, 'default_locale',
                                     translation.get_language())
            self.widgets = [self.widget()]
            value = [Translation(locale=default_locale)]

        if self.is_localized:
            for widget in self.widgets:
                widget.is_localized = self.is_localized

        # value is a list of values, each corresponding to a widget
        # in self.widgets.
        if not isinstance(value, list):
            value = self.decompress(value)

        output = []

        if attrs is None:
            attrs = {}

        final_attrs = self.build_attrs(attrs)
        id_ = final_attrs.get('id', None)
        for i, widget in enumerate(self.widgets):
            try:
                widget_value = value[i]
            except IndexError:
                widget_value = None
            if id_:
                final_attrs = dict(final_attrs, id='%s_%s' % (id_, i))
            output.append(widget.render(
                name + '_%s' % i, widget_value, final_attrs
            ))
        return mark_safe(self.format_output(output))

    def decompress(self, value):
        if not value:
            return []
        elif isinstance(value, (long, int)):
            # We got a foreign key to the translation table.
            qs = Translation.objects.filter(id=value)
            return list(qs.filter(localized_string__isnull=False))
        elif isinstance(value, dict):
            # We're getting a datadict, there was a validation error.
            return [Translation(locale=k, localized_string=v)
                    for k, v in value.items()]

    def value_from_datadict(self, data, files, name):
        # All the translations for this field are called {name}_{locale}, so
        # pull out everything that starts with name.
        rv = {}
        prefix = '%s_' % name

        def locale(s):
            return s[len(prefix):]

        def delete_locale(s):
            return s[len(prefix):-len('_delete')]

        # Look for the name without a locale suffix.
        if name in data:
            rv[translation.get_language()] = data[name]
        # Now look for {name}_{locale}.
        for key in data:
            if key.startswith(prefix):
                if key.endswith('_delete'):
                    rv[delete_locale(key)] = None
                else:
                    rv[locale(key)] = data[key]
        return rv

    def format_output(self, widgets):
        formatted = ''.join(widgets)
        init = self.widget().render(self.name + '_',
                                    Translation(locale='init'),
                                    {'class': 'trans-init'})
        return '<div id="trans-%s" class="trans" data-name="%s">%s%s</div>' % (
            self.name, self.name, formatted, init)


class _TransWidget(object):
    """
    Widget mixin that adds a Translation locale to the lang attribute and the
    input name.
    """

    def render(self, name, value, attrs=None):
        from .fields import switch
        if attrs is None:
            attrs = {}

        attrs = self.build_attrs(attrs)
        lang = to_language(value.locale)
        attrs.update(lang=lang)
        # Use rsplit to drop django's name_idx numbering.  (name_0 => name)
        name = '%s_%s' % (name.rsplit('_', 1)[0], lang)
        # Make sure we don't get a Linkified/Purified Translation. We don't
        # want people editing a bleached value.
        if value.__class__ != Translation:
            value = switch(value, Translation)
        return super(_TransWidget, self).render(name, value, attrs)


# TransInput and TransTextarea are MultiWidgets that know how to set up our
# special translation attributes.
class TransInput(TransMulti):
    widget = type('_TextInput', (_TransWidget, forms.widgets.TextInput), {})


class TransTextarea(TransMulti):
    widget = type('_Textarea', (_TransWidget, forms.widgets.Textarea), {})
