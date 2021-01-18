from django.conf import settings

from django import forms
from django.utils.encoding import force_text
from django.utils.html import conditional_escape, format_html
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext

from olympia.constants.categories import CATEGORIES_BY_ID


class IconTypeSelect(forms.RadioSelect):
    base_html = (
        '<li>'
        '<a href="#" class="{active}">'
        '<img src="{static}img/addon-icons/{icon_name}-32.png" alt="">'
        '</a>'
        '{original_widget}'
        '</li>'
    )

    def render(self, name, value, attrs=None, renderer=None):
        output = []

        for option in self.subwidgets(name, value, attrs):
            option_value = option['value']

            option['widget'] = self.create_option(
                name=name,
                value=option['value'],
                label=option['label'],
                selected=option_value == value,
                index=option['index'],
                attrs=option['attrs'],
            )

            if option_value.split('/')[0] == 'icon' or option_value == '':
                icon_name = option['label']

                original_widget = self._render(self.option_template_name, option)
                if not original_widget.startswith('<label for='):
                    # django2.2+ already wraps widget in a label
                    original_widget = format_html(
                        '<label for="{label_id}">{widget}</label>',
                        label_id=option['widget']['attrs']['id'],
                        widget=original_widget,
                    )
                output.append(
                    format_html(
                        self.base_html,
                        active='active' if option_value == value else '',
                        static=settings.STATIC_URL,
                        icon_name=icon_name,
                        original_widget=original_widget,
                    )
                )
            else:
                output.append(
                    format_html(
                        '<li class="hide">{widget}</li>',
                        widget=self._render(self.option_template_name, option),
                    )
                )

        return mark_safe('\n'.join(output))


class CategoriesSelectMultiple(forms.CheckboxSelectMultiple):
    """Widget that formats the Categories checkboxes."""

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        value = value or []
        has_id = attrs and 'id' in attrs
        final_attrs = self.build_attrs(attrs, {'name': name})

        choices = []
        other = None

        for c in self.choices:
            if CATEGORIES_BY_ID[c[0]].misc:
                msg = ugettext("My add-on doesn't fit into any of the categories")
                other = (c[0], msg)
            else:
                choices.append(c)

        choices = list(enumerate(choices))
        choices_size = len(choices)

        groups = [choices]
        if other:
            groups.append([(choices_size, other)])

        str_values = set([force_text(v) for v in value])

        output = []
        for (k, group) in enumerate(groups):
            cls = 'addon-misc-category' if k == 1 else 'addon-categories'
            output.append('<ul class="%s checkbox-choices">' % cls)

            for i, (option_value, option_label) in group:
                if has_id:
                    final_attrs = dict(final_attrs, id='%s_%s' % (attrs['id'], i))
                    label_for = ' for="%s"' % final_attrs['id']
                else:
                    label_for = ''

                cb = forms.CheckboxInput(
                    final_attrs, check_test=lambda value: value in str_values
                )
                option_value = force_text(option_value)
                rendered_cb = cb.render(name, option_value)
                option_label = conditional_escape(force_text(option_label))
                output.append(
                    '<li><label%s>%s %s</label></li>'
                    % (label_for, rendered_cb, option_label)
                )

            output.append('</ul>')

        return mark_safe('\n'.join(output))
