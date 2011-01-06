from django import forms
from django.conf import settings
from django.utils.encoding import force_unicode
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from tower import ugettext as _

from addons.models import Category


class IconWidgetRenderer(forms.RadioSelect.renderer):
    """ Return radiobox as a list of images. """

    def render(self):
        """ This will output radios as li>img+input. """
        output = []
        for w in self:
            value = w.choice_value
            if value.split('/')[0] == 'icon' or value == '':
                o = (("<li><a href='#' class='%s'><img src='%s/%s-32.png'>"
                      "</a>%s</li>") %
                     ('active' if self.value == w.choice_value else '',
                      settings.ADDON_ICONS_DEFAULT_URL, w.choice_label, w))
            else:
                o = "<li class='hide'>%s</li>" % w
            output.append(o)
        return mark_safe(u'\n'.join(output))


class CategoriesSelectMultiple(forms.CheckboxSelectMultiple):
    """Widget that formats the Categories checkboxes."""

    def __init__(self, **kwargs):
        super(self.__class__, self).__init__(**kwargs)

    def render(self, name, value, attrs=None):
        value = value or []
        has_id = attrs and 'id' in attrs
        final_attrs = self.build_attrs(attrs, name=name)

        choices = []
        other = None

        miscs = Category.objects.filter(misc=True).values_list('id', flat=True)
        for c in self.choices:
            if c[0] in miscs:
                other = (c[0],
                         _("My add-on doesn't fit into any of the categories"))
            else:
                choices.append(c)

        choices = list(enumerate(choices))
        choices_size = len(choices)

        groups = [choices]
        if other:
            groups.append([(choices_size, other)])

        str_values = set([force_unicode(v) for v in value])

        output = []
        for (k, group) in enumerate(groups):
            cls = 'addon-misc-category' if k == 1 else 'addon-categories'
            output.append(u'<ul class="%s">' % cls)

            for i, (option_value, option_label) in group:
                if has_id:
                    final_attrs = dict(final_attrs, id='%s_%s' % (
                            attrs['id'], i))
                    label_for = u' for="%s"' % final_attrs['id']
                else:
                    label_for = ''

                cb = forms.CheckboxInput(
                    final_attrs, check_test=lambda value: value in str_values)
                option_value = force_unicode(option_value)
                rendered_cb = cb.render(name, option_value)
                option_label = conditional_escape(force_unicode(option_label))
                output.append(u'<li><label%s>%s %s</label></li>' % (
                        label_for, rendered_cb, option_label))

            output.append(u'</ul>')

        return mark_safe(u'\n'.join(output))
