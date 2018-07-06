from django.conf import settings

from django import forms
from django.utils.encoding import force_text
from django.utils.html import conditional_escape, format_html_join
from django.utils.translation import ugettext

from olympia.addons.models import Category


class IconTypeSelect(forms.RadioSelect):

    def render(self, name, value, attrs=None, renderer=None):
        output = []

        for option in self.options(name, value, attrs):
            option_value = option['value']
            if option_value.split('/')[0] == 'icon' or option_value == '':
                icon_name = option['label']
                output.append((
                    '<li><a href="#" class="{}">'
                    '<img src="{}img/addon-icons/{}-32.png" alt="">'
                    '</a></li>', (
                        'active' if option_value == value else '',
                        settings.STATIC_URL,
                        icon_name)))
        return format_html_join(output)


class CategoriesSelectMultiple(forms.CheckboxSelectMultiple):
    """Widget that formats the Categories checkboxes."""

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

    def render(self, name, value, attrs=None):
        value = value or []
        has_id = attrs and 'id' in attrs
        final_attrs = self.build_attrs(attrs, {'name': name})

        choices = []
        other = None

        miscs = Category.objects.filter(misc=True).values_list('id', flat=True)
        for c in self.choices:
            if c[0] in miscs:
                msg = ugettext(
                    'My add-on doesn\'t fit into any of the categories')
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
            output.append(u'<ul class="%s checkbox-choices">' % cls)

            for i, (option_value, option_label) in group:
                if has_id:
                    final_attrs = dict(final_attrs,
                                       id='%s_%s' % (attrs['id'], i))
                    label_for = u' for="%s"' % final_attrs['id']
                else:
                    label_for = ''

                cb = forms.CheckboxInput(
                    final_attrs, check_test=lambda value: value in str_values)
                option_value = force_text(option_value)
                rendered_cb = cb.render(name, option_value)
                option_label = conditional_escape(force_text(option_label))
                output.append(u'<li><label%s>%s %s</label></li>' % (
                    label_for, rendered_cb, option_label))

            output.append(u'</ul>')

        return mark_safe(u'\n'.join(output))
